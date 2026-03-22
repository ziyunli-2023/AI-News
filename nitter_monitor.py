"""Nitter monitor — scrapes X user feeds via nitter RSS (no API key needed)."""

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

# Public nitter instances — tried in order, rotated on failure
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
    "https://nitter.net",
]

_STRIP_TAGS = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    text = _STRIP_TAGS.sub(" ", text)
    return html.unescape(" ".join(text.split()))


def _parse_date(entry) -> str:
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


def _fetch_user_feed(username: str, instance: str) -> list[dict] | None:
    """Fetch nitter RSS for one user. Returns None on failure."""
    url = f"{instance}/{username}/rss"
    try:
        resp = httpx.get(
            url, timeout=10, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 AI-News-Monitor/1.0"},
        )
        if resp.status_code != 200:
            return None
        parsed = feedparser.parse(resp.text)
        if not parsed.entries:
            return None
    except Exception:
        return None

    tweets = []
    for entry in parsed.entries[:10]:
        raw_text = entry.get("title", "") or entry.get("summary", "")
        text = _clean(raw_text).strip()
        if not text or text.startswith("RT "):   # skip retweets
            continue

        # Build canonical x.com URL from nitter URL
        nitter_url = entry.get("link", "")
        tweet_id   = nitter_url.rstrip("/").split("/")[-1]
        x_url      = f"https://x.com/{username}/status/{tweet_id}" if tweet_id.isdigit() else nitter_url

        tweets.append({
            "id":           hashlib.sha256(f"{username}::{tweet_id}".encode()).hexdigest()[:16] + tweet_id if tweet_id.isdigit() else hashlib.sha256(nitter_url.encode()).hexdigest(),
            "username":     username.lower(),
            "name":         username,
            "text":         text[:500],
            "created_at":   _parse_date(entry),
            "url":          x_url,
            "likes":        0,
            "retweets":     0,
            "reply_count":  0,
            "lang":         "en",
            "priority_rank": next((u["priority"] for u in config.TRACKED_X_USERS if u["username"].lower() == username.lower()), 2),
            "category":     next((u["category"] for u in config.TRACKED_X_USERS if u["username"].lower() == username.lower()), ""),
        })
    return tweets


class NitterMonitor:
    def __init__(self, on_new_tweet=None):
        self._on_new_tweet = on_new_tweet
        self._stop = threading.Event()
        self._thread = None
        self._instance_idx = 0      # rotate through instances
        self.last_poll_at: str = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="nitter-monitor")
        self._thread.start()
        logger.info("Nitter monitor started (%d accounts)", len(config.TRACKED_X_USERS))

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Nitter monitor stopped")

    def _best_instance(self, username: str) -> list[dict] | None:
        """Try instances in rotation until one succeeds."""
        n = len(NITTER_INSTANCES)
        for i in range(n):
            idx = (self._instance_idx + i) % n
            result = _fetch_user_feed(username, NITTER_INSTANCES[idx])
            if result is not None:
                self._instance_idx = idx   # stick to working instance
                return result
        return None

    def _run(self):
        while not self._stop.is_set():
            new_count = 0
            for user in config.TRACKED_X_USERS:
                if self._stop.is_set():
                    break
                username = user["username"]
                tweets = self._best_instance(username)
                if tweets is None:
                    logger.warning("All nitter instances failed for @%s", username)
                    time.sleep(2)
                    continue
                for tweet in tweets:
                    if storage.save_tweet(tweet):
                        new_count += 1
                        if self._on_new_tweet:
                            self._on_new_tweet(tweet)
                        logger.debug("New post @%s: %s…", username, tweet["text"][:60])
                time.sleep(2)   # polite delay between users

            self.last_poll_at = datetime.utcnow().isoformat()
            if new_count:
                logger.info("Nitter: %d new post(s) this cycle", new_count)
            else:
                logger.debug("Nitter: no new posts this cycle")

            self._stop.wait(config.X_POLL_INTERVAL)
