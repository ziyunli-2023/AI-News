"""Subscription system — subscribers, magic links, sessions.

This module owns all business operations on the three subscription tables
(`subscribers`, `magic_links`, `sessions`). Schema lives in storage.py;
this file just provides higher-level operations on top.

Key concepts
------------
- `Subscriber`         : a person who can receive emails / view gated pages.
- `status`             : 'active' | 'invited' | 'paused' | 'churned'.
                        Only 'active' subscribers receive emails.
- `tier`               : 'free' | 'paid'. Gates content visibility.
- `paid_until`         : ISO timestamp. NULL = no expiry (internal/comp users).
- Magic Link           : 15-min one-time login token, emailed as a clickable URL.
- Session              : 30-day cookie-keyed login, issued after magic-link verify.
"""

import json
import logging
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import config
from storage import get_conn

logger = logging.getLogger(__name__)


# ── Data class ─────────────────────────────────────────────────────────────

@dataclass
class Subscriber:
    id: int
    email: str
    name: Optional[str]
    status: str
    tier: str
    paid_until: Optional[str]
    preferences: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Subscriber":
        prefs: dict = {}
        raw = row["preferences"]
        if raw:
            try:
                prefs = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("subscriber %s has invalid preferences JSON", row["id"])
        return cls(
            id=row["id"],
            email=row["email"],
            name=row["name"],
            status=row["status"],
            tier=row["tier"],
            paid_until=row["paid_until"],
            preferences=prefs,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── Tier check (BUSINESS RULE) ─────────────────────────────────────────────

def is_paid(sub: Optional[Subscriber]) -> bool:
    """Return True if `sub` currently has paid-tier access.

    The three conditions that should all hold:
      1. The account must be active (status == 'active').
         Paused / churned / invited accounts never count as paid.
      2. The tier field must be 'paid'.
      3. If paid_until is set, it must be in the future.
         NULL paid_until means 'no expiry' — used for internal/comp accounts
         and pre-payment users. Treat NULL as "valid forever".

    A `None` subscriber (unauthenticated) is never paid.

    NOTE: this function is the single source of truth for tier gating.
    Both the email rendering path (notifier.py) and the web auth path
    (auth.py:require_paid) call it. Keep the logic here, don't inline.
    """
    if sub is None:
        return False
    if sub.status != "active" or sub.tier != "paid":
        return False
    if sub.paid_until is None:
        return True
    return sub.paid_until > _now()


# ── Subscriber reads ───────────────────────────────────────────────────────

def list_active_subscribers() -> list[Subscriber]:
    """All subscribers eligible to receive digest emails (status='active').

    Used by notifier.py as the source of truth for recipients.
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM subscribers WHERE status = 'active' ORDER BY id"
        ).fetchall()
        return [Subscriber.from_row(r) for r in rows]


def get_by_email(email: str) -> Optional[Subscriber]:
    email = (email or "").lower().strip()
    if not email:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM subscribers WHERE email = ?", (email,)
        ).fetchone()
    return Subscriber.from_row(row) if row else None


def get_by_id(sub_id: int) -> Optional[Subscriber]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM subscribers WHERE id = ?", (sub_id,)
        ).fetchone()
    return Subscriber.from_row(row) if row else None


# ── Subscriber writes ──────────────────────────────────────────────────────

def add_subscriber(email: str, name: str = "", tier: str = "free",
                   status: str = "active",
                   paid_until: Optional[str] = None) -> Subscriber:
    """Insert a new subscriber. Raises sqlite3.IntegrityError on duplicate email."""
    email = email.lower().strip()
    if not email:
        raise ValueError("email is required")
    now = _now()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO subscribers
               (email, name, status, tier, paid_until, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (email, (name or None), status, tier, paid_until, now, now)
        )
        sub_id = cur.lastrowid
    logger.info("Subscriber added: %s (tier=%s, status=%s)", email, tier, status)
    return get_by_id(sub_id)  # type: ignore[return-value]


# ── Magic links ────────────────────────────────────────────────────────────

def create_magic_link(email: str) -> str:
    """Generate a one-time login token for `email`. Caller emails the URL."""
    email = email.lower().strip()
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    expires = now + timedelta(minutes=config.MAGIC_LINK_TTL_MINUTES)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO magic_links (token, email, created_at, expires_at)
               VALUES (?, ?, ?, ?)""",
            (token, email,
             now.isoformat(timespec="seconds"),
             expires.isoformat(timespec="seconds"))
        )
    return token


def consume_magic_link(token: str) -> Optional[str]:
    """Validate & burn a token. Returns the email if valid, else None.

    Uses `WHERE used_at IS NULL` on the UPDATE so concurrent uses can't both
    succeed — at most one caller will get rowcount=1.
    """
    if not token:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT email, expires_at, used_at FROM magic_links WHERE token = ?",
            (token,)
        ).fetchone()
        if not row:
            return None
        if row["used_at"] is not None:
            return None
        if row["expires_at"] < _now():
            return None
        cur = conn.execute(
            "UPDATE magic_links SET used_at = ? WHERE token = ? AND used_at IS NULL",
            (_now(), token)
        )
        if cur.rowcount != 1:
            return None  # someone else just consumed it
        return row["email"]


# ── Sessions ───────────────────────────────────────────────────────────────

def create_session(sub_id: int) -> str:
    """Issue a new session cookie value for the subscriber."""
    session_id = secrets.token_urlsafe(32)
    now = datetime.now()
    expires = now + timedelta(days=config.SESSION_TTL_DAYS)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sessions
               (id, subscriber_id, created_at, expires_at, last_seen)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, sub_id,
             now.isoformat(timespec="seconds"),
             expires.isoformat(timespec="seconds"),
             now.isoformat(timespec="seconds"))
        )
    return session_id


def get_by_session(session_id: Optional[str]) -> Optional[Subscriber]:
    """Resolve a session cookie to a Subscriber. None if missing/expired."""
    if not session_id:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT subscriber_id, expires_at FROM sessions WHERE id = ?",
            (session_id,)
        ).fetchone()
        if not row:
            return None
        if row["expires_at"] < _now():
            return None
        # Touch last_seen — best-effort, don't crash auth on update failures
        try:
            conn.execute(
                "UPDATE sessions SET last_seen = ? WHERE id = ?",
                (_now(), session_id)
            )
        except Exception:
            pass
        sub_id = row["subscriber_id"]
    return get_by_id(sub_id)


def expire_session(session_id: Optional[str]) -> None:
    """Delete a session row (logout). No-op for unknown/empty IDs."""
    if not session_id:
        return
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


# ── One-time seed from EMAIL_RECIPIENTS env ────────────────────────────────

def seed_initial_subscribers() -> int:
    """Bootstrap the subscribers table from config.EMAIL_RECIPIENTS.

    Runs once when the table is empty. Each existing recipient is added as
    `status='active', tier='paid', paid_until=NULL` so that current digest
    behavior is preserved across the schema migration. Returns the number
    of rows actually inserted (0 if the table was already non-empty).
    """
    with get_conn() as conn:
        existing = conn.execute("SELECT COUNT(*) AS n FROM subscribers").fetchone()
        if existing["n"] > 0:
            return 0
    inserted = 0
    for email in config.EMAIL_RECIPIENTS:
        if not email:
            continue
        try:
            add_subscriber(email=email, tier="paid", status="active")
            inserted += 1
        except sqlite3.IntegrityError:
            # Race or pre-existing row — fine, skip silently
            pass
    if inserted:
        logger.info("Seeded %d subscriber(s) from EMAIL_RECIPIENTS", inserted)
    return inserted
