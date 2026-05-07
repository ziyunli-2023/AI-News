"""Polymarket monitor — polls trending prediction markets and stores them as posts."""

import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timezone

import httpx

import config
import storage

logger = logging.getLogger(__name__)

_API_URL = "https://gamma-api.polymarket.com/markets"
_MARKET_BASE = "https://polymarket.com/event/"


def _fmt_volume(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v:.0f}"


def _build_summary(market: dict) -> str:
    parts = []
    try:
        outcomes = json.loads(market.get("outcomes") or "[]")
        prices   = json.loads(market.get("outcomePrices") or "[]")
        if outcomes and prices and len(outcomes) == len(prices):
            probs = [f"{o} {float(p)*100:.0f}%" for o, p in zip(outcomes, prices)]
            parts.append("Odds: " + " / ".join(probs))
    except Exception:
        pass
    vol = _fmt_volume(market.get("volume24hr") or market.get("volume"))
    if vol:
        parts.append(f"24h Vol: {vol}")
    liq = _fmt_volume(market.get("liquidity"))
    if liq:
        parts.append(f"Liquidity: {liq}")
    end = market.get("endDate", "")
    if end:
        parts.append(f"Ends: {end[:10]}")
    desc = (market.get("description") or "").strip()
    if desc:
        parts.append(desc[:200])
    return " | ".join(parts)


def _market_id(market: dict) -> str:
    slug = market.get("slug") or market.get("id") or market.get("question", "")
    return hashlib.sha256(f"polymarket::{slug}".encode()).hexdigest()


def _market_url(market: dict) -> str:
    # Polymarket website URLs use the event slug, not the market slug
    events = market.get("events") or []
    if events and events[0].get("slug"):
        return _MARKET_BASE + events[0]["slug"]
    slug = market.get("slug") or ""
    return _MARKET_BASE + slug if slug else "https://polymarket.com"


# Topics recognizable to both Eastern and Western audiences.
# Higher score = higher priority when sorting for display/briefing.
_GLOBAL_TOPICS = [
    # Geopolitics & world leaders
    (10, ["trump", "biden", "xi jinping", "putin", "zelensky", "ukraine", "russia", "china",
          "taiwan", "north korea", "iran", "israel", "gaza", "middle east", "nato",
          "war", "ceasefire", "sanctions", "nuclear"]),
    # Global economy & markets — use word-boundary-safe tokens
    (8,  ["federal reserve", "interest rate", "rate cut", "recession", "inflation",
          "gdp", "tariff", "trade war", "imf", "world bank", "oil price", " gold ",
          "the fed ", "fed rate", "fomc"]),
    # AI & big tech (global)
    (8,  ["openai", "chatgpt", "gpt-", "anthropic", "gemini", "artificial intelligence",
          "nvidia", "apple inc", "microsoft", "google", "meta ai", "amazon", "tesla",
          "spacex", "elon musk", "sam altman"]),
    # Crypto (globally followed)
    (7,  ["bitcoin", "btc", "ethereum", "crypto", "coinbase", "binance"]),
    # Major global elections — only known major countries/leaders
    (6,  ["us election", "presidential election 2028", "presidential race",
          "uk election", "french election", "german election",
          "modi", "macron", "scholz", "starmer"]),
    # Other truly global events
    (4,  ["world cup", "olympics", "nobel prize", "g7", "g20", "un summit"]),
]

_NICHE_PENALTY = [
    "nba", "nfl", "mlb", "nhl", "super bowl", "oscars", "grammy", "emmy",
    "box office", "rapper", "celebrity", "kardashian", "bachelor",
    "governor", "senate", "congress", "house rep",   # US domestic politics
]

# Topics to block entirely — never show regardless of score
_BLOCKED_TOPICS = [
    "china invade taiwan", "invade taiwan", "taiwan invasion",
    "xi jinping", "ccp", "chinese communist", "china's president",
    "china president", "china attack", "pla ", "people's liberation",
    "hong kong", "tiananmen", "xinjiang", "tibet",
]

_TOPIC_CLUSTERS = [
    ("iran",         ["iran"]),
    ("ukraine",      ["ukraine", "zelensky"]),
    ("russia",       ["russia", "putin"]),
    ("china_taiwan", ["taiwan", "xi jinping"]),
    ("trump",        ["trump"]),
    ("bitcoin",      ["bitcoin", "btc"]),
    ("ethereum",     ["ethereum", " eth "]),
    ("fed",          ["federal reserve", " fed ", "rate cut", "interest rate"]),
    ("north_korea",  ["north korea"]),
    ("israel_gaza",  ["israel", "gaza"]),
]


def _topic_cluster(q: str) -> str:
    ql = q.lower()
    for cluster, keywords in _TOPIC_CLUSTERS:
        if any(k in ql for k in keywords):
            return cluster
    return q[:30]


def _global_score(question: str, volume24hr) -> float:
    q = question.lower()
    score = 0.0
    for pts, keywords in _GLOBAL_TOPICS:
        if any(k in q for k in keywords):
            score += pts
    for k in _NICHE_PENALTY:
        if k in q:
            score -= 6
    # Volume bonus: log scale so a $1M market beats a $10K one but not 10x
    try:
        import math
        v = float(volume24hr or 0)
        if v > 0:
            score += math.log10(v) * 0.5
    except Exception:
        pass
    return score


def _fetch_markets() -> list[dict]:
    params = {
        "active": "true",
        "closed": "false",
        "limit": 50,
        "order": "volume24hr",
        "ascending": "false",
    }
    try:
        resp = httpx.get(
            _API_URL,
            params=params,
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": "AI-News-Monitor/1.0"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Polymarket fetch failed: %s", e)
        return []

    raw = []
    for m in (data if isinstance(data, list) else data.get("markets", [])):
        question = (m.get("question") or "").strip()
        if not question:
            continue
        ql = question.lower()
        if any(b in ql for b in _BLOCKED_TOPICS):
            continue
        score = _global_score(question, m.get("volume24hr") or m.get("volume", 0))
        raw.append((score, m, question))

    # Sort by global relevance score descending
    raw.sort(key=lambda x: x[0], reverse=True)

    # Topic deduplication: max 2 per cluster so one hot topic doesn't dominate
    cluster_counts: dict[str, int] = {}
    posts = []
    for score, m, question in raw:
        if score <= 0:
            continue  # skip niche/unrecognized topics entirely
        cluster = _topic_cluster(question)
        if cluster_counts.get(cluster, 0) >= 2:
            continue
        cluster_counts[cluster] = cluster_counts.get(cluster, 0) + 1
        posts.append({
            "id": _market_id(m),
            "source": "Polymarket",
            "title": question,
            "url": _market_url(m),
            "summary": _build_summary(m),
            "published": m.get("startDate") or datetime.now(timezone.utc).isoformat(),
            "feed_priority": 2,
            "category": "polymarket",
            "alert": False,
            "is_paper": False,
            "arxiv_id": None,
        })
    return posts


class PolymarketMonitor:
    def __init__(self, on_new_post=None):
        self._on_new_post = on_new_post
        self._stop = threading.Event()
        self._thread = None
        self.last_poll_at: str = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="polymarket-monitor")
        self._thread.start()
        logger.info("Polymarket monitor started")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Polymarket monitor stopped")

    def _run(self):
        while not self._stop.is_set():
            posts = _fetch_markets()
            new_count = 0
            for post in posts:
                if storage.save_post(post):
                    new_count += 1
                    if self._on_new_post:
                        self._on_new_post(post)
                    logger.debug("New Polymarket market: %s", post["title"][:80])

            self.last_poll_at = datetime.utcnow().isoformat()
            if new_count:
                logger.info("Polymarket: %d new market(s)", new_count)
            else:
                logger.debug("Polymarket: no new markets")

            self._stop.wait(config.POLYMARKET_POLL_INTERVAL)
