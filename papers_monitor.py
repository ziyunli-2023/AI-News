"""Papers monitor — fetches AI papers from HF Daily Papers + HF Org papers,
plus refreshes engagement signals (HF upvotes, HN score) on hot papers.

Stores everything into the existing `blog_posts` table with `is_paper=1`.
Reuses storage.save_post() for dedup; reuses translation worker for zh fields.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx

import config
import storage

logger = logging.getLogger(__name__)

HF_API_BASE = "https://huggingface.co/api"
HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"

# How many days of HF Daily Papers to scan on each cycle. Hot papers tend to
# accumulate upvotes over 2–3 days, so we scan a 7-day window to keep their
# scores fresh while still bounding API load.
HF_DAILY_LOOKBACK_DAYS = 7

# 用户优先级: 大模型公司技术报告 > 顶级实验室 > 其他
# Tier 1: 出 SOTA 模型的大模型公司 — 最高加成 (+15)
MODEL_COMPANY_KEYWORDS = {
    # 海外
    "openai", "anthropic", "deepmind", "google deepmind",
    "meta ai", "fair ", "facebook ai",
    "mistral", "xai", "x.ai", "stability ai", "runway",
    # 中国大模型公司
    "deepseek", "qwen", "alibaba", "bytedance", "doubao", "seed-", "byte-seed",
    "moonshot", "kimi", "zhipu", "thudm", "glm-", "01-ai", "01.ai", "yi-",
    "baichuan",
}

# Tier 2: 顶级实验室 (大公司研究院 + 学术) — 中等加成 (+5)
RESEARCH_LAB_KEYWORDS = {
    "microsoft research", "msr ", "apple ml", "apple machine learning",
    "allen institute", "ai2 ", "cohere", "nvidia research",
    "tencent", "baidu",
    "mit ", "stanford", "berkeley", "cmu", "carnegie mellon",
    "princeton", "harvard", "oxford", "cambridge", "eth zurich",
    "tsinghua", "peking university", "sjtu", "fudan",
}


def _hours_since(iso_str: str) -> float:
    """Hours between an ISO timestamp and now (UTC). Missing/bad → 9999."""
    if not iso_str:
        return 9999.0
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 9999.0


# ── Scoring ────────────────────────────────────────────────────────────────

def compute_paper_score(post: dict) -> float:
    """Rank a paper by a weighted blend of: source tier, community signal, recency.

    Priority (highest → lowest):
      1. 大模型公司技术报告 (DeepSeek, Qwen, OpenAI, …)  → +15 tier bonus
      2. 顶级实验室 (MSR, Apple, AI2, top universities)   → +5  tier bonus
      3. Community signal: log-scaled HF upvotes (×10) + HN score (×3).
         Log scale stops a single viral paper from dominating top-N.
      4. Recency: 6h head-start for brand-new posts (so 0-upvote new papers
         from frontier labs surface before the community reacts), then linear
         decay to 0 by 72h.
    """
    import math

    haystack = " ".join(filter(None, (
        (post.get("source")  or "").lower(),
        (post.get("authors") or "").lower(),
        (post.get("title")   or "").lower(),
        (post.get("summary") or "").lower(),
    )))

    if any(k in haystack for k in MODEL_COMPANY_KEYWORDS):
        tier_bonus = 15.0
    elif any(k in haystack for k in RESEARCH_LAB_KEYWORDS):
        tier_bonus = 5.0
    else:
        tier_bonus = 0.0

    score = math.log1p(int(post.get("hf_upvotes") or 0)) * 10
    score += math.log1p(int(post.get("hn_score")   or 0)) * 3

    hours = _hours_since(post.get("published") or post.get("fetched_at"))
    if hours < 6:
        score += 8
    elif hours < 72:
        score += 6 * (1 - hours / 72)

    return score + tier_bonus


# ── HF Daily Papers ────────────────────────────────────────────────────────

def _hf_paper_to_post(item: dict, source_label: str = "HF Daily") -> dict | None:
    """Convert one HF API item (Daily Papers or Org papers) into a post dict."""
    paper = item.get("paper") or item
    arxiv_id = paper.get("id") or ""
    title = (paper.get("title") or "").strip()
    if not arxiv_id or not title:
        return None
    summary = (paper.get("summary") or "").strip()
    upvotes = int(paper.get("upvotes") or 0)
    authors_list = paper.get("authors") or []
    authors_names = [a.get("name", "") for a in authors_list if isinstance(a, dict)]
    published = (
        paper.get("publishedAt")
        or item.get("publishedAt")
        or paper.get("submittedOnDailyAt")
        or ""
    )

    arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
    pdf_url   = f"https://arxiv.org/pdf/{arxiv_id}"
    post_id = hashlib.sha256(f"hf_paper::{arxiv_id}".encode()).hexdigest()

    post = {
        "id": post_id,
        "source": source_label,
        "title": title,
        "url": arxiv_url,
        "summary": summary[:500],
        "published": published,
        "feed_priority": 1,
        "category": "papers",
        "is_paper": True,
        "arxiv_id": arxiv_id,
        "hf_paper_id": arxiv_id,  # HF uses the arXiv id as paper id
        "hf_upvotes": upvotes,
        "authors": json.dumps(authors_names, ensure_ascii=False) if authors_names else None,
        "pdf_url": pdf_url,
    }
    post["paper_score"] = compute_paper_score(post)
    return post


def _http_get_json(url: str, params: dict = None, timeout: float = 15.0) -> list | dict | None:
    try:
        resp = httpx.get(
            url,
            params=params,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "AI-News-Monitor/1.0"},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("HTTP GET %s failed: %s", url, e)
        return None


def fetch_hf_daily(date_str: str) -> list[dict]:
    """Fetch HF Daily Papers JSON for one ISO date (YYYY-MM-DD)."""
    data = _http_get_json(f"{HF_API_BASE}/daily_papers", params={"date": date_str})
    if not isinstance(data, list):
        return []
    posts = []
    for item in data:
        post = _hf_paper_to_post(item, source_label="HF Daily")
        if post:
            posts.append(post)
    storage.record_feed_success("HF Daily")
    return posts


def fetch_hf_org_papers(org_id: str, label: str) -> list[dict]:
    """Fetch the papers tab of one HF organization."""
    data = _http_get_json(f"{HF_API_BASE}/papers", params={"author": org_id})
    if not isinstance(data, list):
        storage.record_feed_error(label, "non-list response or fetch failed")
        return []
    posts = []
    for item in data[:25]:
        post = _hf_paper_to_post(item, source_label=label)
        if post:
            post["feed_priority"] = 2
            posts.append(post)
    storage.record_feed_success(label)
    return posts


# ── Hacker News ────────────────────────────────────────────────────────────

def fetch_hn_arxiv_scores() -> dict[str, int]:
    """Return {arxiv_id: hn_score} for arXiv links recently posted to HN."""
    data = _http_get_json(
        HN_ALGOLIA_URL,
        params={
            "query": "arxiv.org",
            "tags": "story",
            "numericFilters": "points>30",
            "hitsPerPage": 100,
        },
    )
    if not data or "hits" not in data:
        return {}
    import re
    pat = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,6})")
    out: dict[str, int] = {}
    for hit in data["hits"]:
        url = hit.get("url") or ""
        m = pat.search(url)
        if not m:
            continue
        aid = m.group(1)
        pts = int(hit.get("points") or 0)
        if pts > out.get(aid, 0):
            out[aid] = pts
    storage.record_feed_success("HN Algolia")
    return out


# ── Refresh existing papers' metrics ───────────────────────────────────────

def refresh_paper_metrics() -> int:
    """Re-poll HF for upvotes on recently-fetched papers and recompute scores.
    Returns number of rows updated."""
    rows = storage.get_papers_for_refresh(hours=72)
    if not rows:
        return 0
    arxiv_ids = [r["arxiv_id"] or r["hf_paper_id"] for r in rows if r.get("arxiv_id") or r.get("hf_paper_id")]
    if not arxiv_ids:
        return 0

    # Bulk fetch by querying HF /api/papers/{id}
    upvote_by_id: dict[str, int] = {}
    for aid in arxiv_ids[:60]:  # cap per cycle
        data = _http_get_json(f"{HF_API_BASE}/papers/{aid}")
        if isinstance(data, dict):
            upvote_by_id[aid] = int(data.get("upvotes") or 0)
        time.sleep(0.2)

    hn_scores = fetch_hn_arxiv_scores()

    updated = 0
    for r in rows:
        aid = r["arxiv_id"] or r["hf_paper_id"]
        if not aid:
            continue
        new_uv = upvote_by_id.get(aid, r.get("hf_upvotes") or 0)
        new_hn = hn_scores.get(aid, r.get("hn_score") or 0)
        merged = dict(r, hf_upvotes=new_uv, hn_score=new_hn)
        new_score = compute_paper_score(merged)
        storage.update_paper_metrics(
            r["id"], hf_upvotes=new_uv, hn_score=new_hn, paper_score=new_score,
        )
        updated += 1
    return updated


# ── Daemon ─────────────────────────────────────────────────────────────────

class PapersMonitor:
    def __init__(self, on_new_post=None):
        self._on_new_post = on_new_post
        self._stop = threading.Event()
        self._thread = None
        self._last_daily = 0.0
        self._last_lab   = 0.0
        self._last_refresh = 0.0
        self.last_poll_at: str | None = None

    def start(self):
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="papers-monitor",
        )
        self._thread.start()
        logger.info(
            "Papers monitor started (HF Daily + %d labs)", len(config.PAPER_LAB_ORG_IDS),
        )

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Papers monitor stopped")

    def _run(self):
        # Initial kick after small delay (so other monitors can boot)
        self._stop.wait(15)
        while not self._stop.is_set():
            now = time.time()

            if now - self._last_daily >= config.PAPERS_DAILY_INTERVAL:
                self._poll_hf_daily()
                self._last_daily = time.time()

            if now - self._last_lab >= config.PAPERS_LAB_INTERVAL:
                self._poll_hf_orgs()
                self._last_lab = time.time()

            if now - self._last_refresh >= config.PAPERS_REFRESH_INTERVAL:
                try:
                    n = refresh_paper_metrics()
                    if n:
                        logger.info("Papers: refreshed metrics on %d row(s)", n)
                except Exception as e:
                    logger.warning("refresh_paper_metrics failed: %s", e)
                self._last_refresh = time.time()

            self.last_poll_at = datetime.utcnow().isoformat()
            self._stop.wait(60)

    def _poll_hf_daily(self):
        today = datetime.now(timezone.utc).date()
        new_count = 0
        for delta in range(HF_DAILY_LOOKBACK_DAYS):
            if self._stop.is_set():
                break
            d = today - timedelta(days=delta)
            posts = fetch_hf_daily(d.isoformat())
            for p in posts:
                if storage.save_post(p):
                    new_count += 1
                    if self._on_new_post:
                        try:
                            self._on_new_post(p)
                        except Exception as e:
                            logger.debug("on_new_post callback failed: %s", e)
            time.sleep(1)
        if new_count:
            logger.info("HF Daily Papers: %d new", new_count)

    def _poll_hf_orgs(self):
        new_count = 0
        for org_id, label in config.PAPER_LAB_ORG_IDS.items():
            if self._stop.is_set():
                break
            posts = fetch_hf_org_papers(org_id, label)
            for p in posts:
                if storage.save_post(p):
                    new_count += 1
                    if self._on_new_post:
                        try:
                            self._on_new_post(p)
                        except Exception as e:
                            logger.debug("on_new_post callback failed: %s", e)
            time.sleep(1)
        if new_count:
            logger.info("HF Org Papers: %d new across %d labs",
                        new_count, len(config.PAPER_LAB_ORG_IDS))
