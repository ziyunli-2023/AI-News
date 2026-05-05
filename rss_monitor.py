"""RSS feed monitor — polls configured feeds and stores new posts."""

import hashlib
import html
import logging
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

import config
import storage

logger = logging.getLogger(__name__)

_STRIP_TAGS = re.compile(r"<[^>]+>")
_ARXIV_ID_RE = re.compile(r"arxiv\.org/abs/([0-9]{4}\.[0-9]{4,6}(?:v\d+)?)", re.I)


def _extract_arxiv_id(url: str) -> str | None:
    m = _ARXIV_ID_RE.search(url or "")
    return m.group(1).split("v")[0] if m else None


def _parse_date(entry) -> str:
    """Best-effort date extraction from a feedparser entry."""
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    for attr in ("published", "updated"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return parsedate_to_datetime(val).isoformat()
            except Exception:
                pass
    return datetime.now(timezone.utc).isoformat()


def _entry_id(entry, source: str) -> str:
    """Stable unique ID for a feed entry."""
    raw = entry.get("id") or entry.get("link") or entry.get("title", "")
    return hashlib.sha256(f"{source}::{raw}".encode()).hexdigest()


def _clean_html(text: str) -> str:
    """Strip HTML tags and decode entities."""
    text = _STRIP_TAGS.sub(" ", text)
    text = html.unescape(text)
    return " ".join(text.split())[:500]


def _passes_arxiv_filter(title: str, summary: str) -> bool:
    """Only store arXiv papers that (a) match a topic keyword AND
    (b) mention a top-tier lab/institution in title/summary.
    Cuts ~80% of daily arXiv volume while keeping frontier work."""
    combined = (title + " " + summary).lower()
    if not any(kw in combined for kw in config.ARXIV_KEYWORDS):
        return False
    return any(org in combined for org in config.ARXIV_AUTHOR_WHITELIST)


def _fetch_feed(feed_cfg: dict) -> list[dict]:
    name = feed_cfg["name"]
    url = feed_cfg["url"]
    is_arxiv = feed_cfg.get("is_arxiv", False)
    tier = feed_cfg.get("tier", 2)
    category = feed_cfg.get("category", "ai")
    alert = feed_cfg.get("alert", False)

    try:
        resp = httpx.get(
            url, timeout=15, follow_redirects=True,
            headers={"User-Agent": "AI-News-Monitor/1.0"},
        )
        resp.raise_for_status()
        parsed = feedparser.parse(resp.text)
        storage.record_feed_success(name)
    except Exception as e:
        logger.warning("Failed to fetch '%s': %s", name, e)
        storage.record_feed_error(name, e)
        return []

    posts = []
    for entry in parsed.entries[:20]:
        title = entry.get("title", "").strip()
        link  = entry.get("link", "").strip()
        if not title or not link:
            continue

        raw_summary = entry.get("summary", "") or entry.get("description", "")
        summary = _clean_html(raw_summary)

        # ArXiv keyword filter
        if is_arxiv and not _passes_arxiv_filter(title, summary):
            continue

        # Mark paper-type posts. Includes arXiv (always) and lab tech-report
        # feeds (anything in category "papers").
        is_paper = bool(is_arxiv or category == "papers")
        arxiv_id = _extract_arxiv_id(link) if is_paper else None

        posts.append(
            {
                "id": _entry_id(entry, name),
                "source": name,
                "title": title,
                "url": link,
                "summary": summary,
                "published": _parse_date(entry),
                "feed_priority": tier,
                "category": category,
                "alert": alert,
                "is_paper": is_paper,
                "arxiv_id": arxiv_id,
            }
        )
    return posts


class RSSMonitor:
    def __init__(self, on_new_post=None):
        self._on_new_post = on_new_post  # callback(post_dict)
        self._stop = threading.Event()
        self._thread = None
        # Track when each feed was last polled: {feed_name: timestamp}
        self._last_polled: dict[str, float] = {}
        self.last_poll_at: str = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="rss-monitor")
        self._thread.start()
        logger.info("RSS monitor started (%d feeds)", len(config.RSS_FEEDS))

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("RSS monitor stopped")

    def _run(self):
        while not self._stop.is_set():
            now = time.time()
            new_count = 0

            for feed_cfg in config.RSS_FEEDS:
                if self._stop.is_set():
                    break

                name = feed_cfg["name"]
                tier = feed_cfg.get("tier", 2)
                interval = config.RSS_POLL_INTERVALS.get(tier, 3600)
                last = self._last_polled.get(name, 0)

                # Skip if not due yet
                if now - last < interval:
                    continue

                posts = _fetch_feed(feed_cfg)
                self._last_polled[name] = time.time()

                for post in posts:
                    if storage.save_post(post):
                        new_count += 1
                        if self._on_new_post:
                            self._on_new_post(post)
                        logger.debug("New post [%s]: %s", post["source"], post["title"][:80])

                time.sleep(1)  # polite delay between feeds

            self.last_poll_at = datetime.utcnow().isoformat()
            if new_count:
                logger.info("RSS: %d new post(s) this cycle", new_count)
            else:
                logger.debug("RSS: no new posts this cycle")

            # Sleep 60s between checks (actual per-feed interval enforced above)
            self._stop.wait(60)
