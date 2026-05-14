"""Earnings calendar monitor — daily refresh from Finnhub free tier.

Pulls:
- /calendar/earnings  → upcoming corporate earnings reports
- /calendar/ipo       → upcoming IPOs
- /stock/profile2     → market-cap + industry enrichment (cached 30 days)

Also loads US macro events (CPI/FOMC/NFP/PCE/GDP) from data/us_macro_events.json
because Finnhub's /calendar/economic is premium-only.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx

import config
import storage

logger = logging.getLogger(__name__)

_BASE = "https://finnhub.io/api/v1"
_MACRO_FILE = os.path.join(os.path.dirname(__file__), "data", "us_macro_events.json")


def _get(path: str, params: dict | None = None, timeout: int = 20) -> dict | None:
    if not config.FINNHUB_API_KEY:
        return None
    p = dict(params or {})
    p["token"] = config.FINNHUB_API_KEY
    try:
        resp = httpx.get(_BASE + path, params=p, timeout=timeout,
                         headers={"User-Agent": "YunFlow/1.0"})
        if resp.status_code == 429:
            logger.warning("Finnhub rate-limited (%s); sleeping 30s", path)
            time.sleep(30)
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("Finnhub GET %s failed: %s", path, e)
        return None


def fetch_earnings(from_date: str, to_date: str) -> list[dict]:
    data = _get("/calendar/earnings", {"from": from_date, "to": to_date})
    if not data:
        return []
    rows = []
    for r in data.get("earningsCalendar") or []:
        sym = r.get("symbol")
        date = r.get("date")
        if not sym or not date:
            continue
        rows.append({
            "id":           f"earnings::{sym}::{date}",
            "symbol":       sym,
            "date":         date,
            "hour":         r.get("hour"),
            "eps_estimate": r.get("epsEstimate"),
            "eps_actual":   r.get("epsActual"),
            "rev_estimate": r.get("revenueEstimate"),
            "rev_actual":   r.get("revenueActual"),
            "quarter":      r.get("quarter"),
            "year":         r.get("year"),
        })
    logger.info("Finnhub earnings: %d rows (%s → %s)", len(rows), from_date, to_date)
    return rows


def fetch_ipos(from_date: str, to_date: str) -> list[dict]:
    data = _get("/calendar/ipo", {"from": from_date, "to": to_date})
    if not data:
        return []
    rows = []
    for r in data.get("ipoCalendar") or []:
        name = r.get("name") or r.get("symbol")
        date = r.get("date")
        if not name or not date:
            continue
        sym = (r.get("symbol") or "").strip() or None
        key = sym or name.replace(" ", "_")[:30]
        rows.append({
            "id":          f"ipo::{key}::{date}",
            "symbol":      sym,
            "name":        name,
            "date":        date,
            "exchange":    r.get("exchange"),
            "price_range": r.get("price"),
            "shares":      r.get("numberOfShares"),
            "total_value": r.get("totalSharesValue"),
            "status":      r.get("status"),
        })
    logger.info("Finnhub IPOs: %d rows (%s → %s)", len(rows), from_date, to_date)
    return rows


def enrich_profiles(symbols: list[str]) -> int:
    """Fetch /stock/profile2 for any symbols missing a fresh profile. Rate-limited."""
    stale = storage.get_symbols_needing_profile(symbols, max_age_days=config.EARNINGS_PROFILE_TTL_DAYS)
    if not stale:
        return 0
    logger.info("Enriching %d profiles", len(stale))
    n_ok = 0
    for sym in stale:
        prof = _get("/stock/profile2", {"symbol": sym})
        if prof and prof.get("ticker"):
            storage.upsert_profile(sym, prof)
            n_ok += 1
        else:
            # Persist a placeholder so we don't keep retrying empty symbols every day
            storage.upsert_profile(sym, {})
        time.sleep(1.1)  # stay under 60 req/min
    logger.info("Profile enrichment: %d/%d succeeded", n_ok, len(stale))
    return n_ok


def fetch_company_news(symbol: str, days: int = 14, limit: int = 10) -> list[dict]:
    """Pull Finnhub /company-news for a ticker. Returns normalized items.

    Free tier: this endpoint is included. Returns up to ~50 items per call.
    Returns [] if no API key or call fails — caller should treat as soft failure.
    """
    if not config.FINNHUB_API_KEY or not symbol:
        return []
    today = datetime.now(timezone.utc).date()
    frm = (today - timedelta(days=days)).isoformat()
    data = _get("/company-news", {"symbol": symbol, "from": frm, "to": today.isoformat()})
    if not isinstance(data, list):
        return []
    out = []
    for n in data[:limit]:
        ts = n.get("datetime")
        try:
            iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None
        except Exception:
            iso = None
        out.append({
            "source":   n.get("source") or "Finnhub",
            "title":    n.get("headline") or "",
            "summary":  n.get("summary") or "",
            "url":      n.get("url") or "",
            "published": iso,
            "image":    n.get("image") or None,
        })
    return out


def load_macro_events() -> int:
    try:
        with open(_MACRO_FILE, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as e:
        logger.warning("macro events JSON load failed: %s", e)
        return 0
    events = doc.get("events") if isinstance(doc, dict) else doc
    return storage.upsert_macro_events(events or [])


def refresh_cycle() -> dict:
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=config.EARNINGS_WINDOW_DAYS)
    start_str = today.isoformat()
    end_str = end.isoformat()

    earnings = fetch_earnings(start_str, end_str)
    storage.upsert_earnings(earnings)

    ipos = fetch_ipos(start_str, end_str)
    storage.upsert_ipos(ipos)

    # Enrich profiles for any new symbols
    symbols = sorted({r["symbol"] for r in earnings if r.get("symbol")})
    n_profiles = enrich_profiles(symbols)

    n_macro = load_macro_events()

    return {
        "earnings": len(earnings),
        "ipos": len(ipos),
        "profiles_enriched": n_profiles,
        "macro": n_macro,
    }


class EarningsMonitor:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = None
        self.last_run_at: str | None = None
        self.last_result: dict | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="earnings-monitor")
        self._thread.start()
        logger.info("Earnings monitor started")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _run(self):
        if not config.FINNHUB_API_KEY:
            logger.warning("FINNHUB_API_KEY not set — earnings monitor will only load macro JSON")

        # Initial fetch on startup (so the page works immediately)
        self._tick()

        while not self._stop.is_set():
            # Sleep until the next refresh hour
            now = datetime.now(timezone.utc)
            target = now.replace(hour=config.EARNINGS_REFRESH_HOUR, minute=0, second=0, microsecond=0)
            if target <= now:
                target = target + timedelta(days=1)
            delay = (target - now).total_seconds()
            if self._stop.wait(delay):
                return
            self._tick()

    def _tick(self):
        try:
            self.last_result = refresh_cycle()
            self.last_run_at = datetime.now(timezone.utc).isoformat()
            logger.info("Earnings refresh: %s", self.last_result)
        except Exception as e:
            logger.exception("Earnings refresh failed: %s", e)
