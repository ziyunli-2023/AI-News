"""SQLite storage with deduplication."""

import hashlib
import sqlite3
from datetime import datetime
from contextlib import contextmanager
import config


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn):
    """Add columns introduced after initial schema."""
    for ddl in (
        "ALTER TABLE blog_posts ADD COLUMN category TEXT",
        "ALTER TABLE tweets ADD COLUMN text_zh TEXT",
    ):
        try:
            conn.execute(ddl)
            conn.commit()
        except Exception:
            pass  # column already exists


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tweets (
                id            TEXT PRIMARY KEY,
                username      TEXT NOT NULL,
                name          TEXT,
                text          TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                url           TEXT,
                likes         INTEGER DEFAULT 0,
                retweets      INTEGER DEFAULT 0,
                reply_count   INTEGER DEFAULT 0,
                lang          TEXT,
                priority_rank INTEGER DEFAULT 2,
                category      TEXT,
                fetched_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS blog_posts (
                id            TEXT PRIMARY KEY,
                source        TEXT NOT NULL,
                title         TEXT NOT NULL,
                url           TEXT NOT NULL,
                summary       TEXT,
                published     TEXT,
                feed_priority INTEGER DEFAULT 2,
                content_hash  TEXT,
                title_zh      TEXT,
                summary_zh    TEXT,
                category      TEXT,
                fetched_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS x_cursors (
                user_id    TEXT PRIMARY KEY,
                username   TEXT NOT NULL,
                since_id   TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS feed_health (
                source               TEXT PRIMARY KEY,
                last_success         TEXT,
                last_error           TEXT,
                consecutive_failures INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_tweets_created   ON tweets(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_tweets_user      ON tweets(username);
            CREATE INDEX IF NOT EXISTS idx_tweets_priority  ON tweets(priority_rank);
            CREATE INDEX IF NOT EXISTS idx_tweets_category  ON tweets(category);
            CREATE INDEX IF NOT EXISTS idx_posts_published  ON blog_posts(published DESC);
            CREATE INDEX IF NOT EXISTS idx_posts_source     ON blog_posts(source);
            CREATE INDEX IF NOT EXISTS idx_posts_priority   ON blog_posts(feed_priority);
            CREATE INDEX IF NOT EXISTS idx_posts_hash       ON blog_posts(content_hash);
        """)
        _migrate(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_category ON blog_posts(category)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS digest_log (
                date    TEXT NOT NULL,
                hour    INTEGER NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (date, hour)
            )
        """)


def _content_hash(title: str) -> str:
    """Normalized title hash for cross-source deduplication."""
    import re
    normalized = re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


# ── Cursor persistence ─────────────────────────────────────────────────────

def load_cursors() -> dict[str, str]:
    """Load {user_id: since_id} from DB."""
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id, since_id FROM x_cursors").fetchall()
        return {r["user_id"]: r["since_id"] for r in rows}


def save_cursor(user_id: str, username: str, since_id: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO x_cursors (user_id, username, since_id, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   since_id=excluded.since_id,
                   updated_at=excluded.updated_at""",
            (user_id, username, since_id, datetime.utcnow().isoformat()),
        )


# ── Feed health ────────────────────────────────────────────────────────────

def record_feed_success(source: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO feed_health (source, last_success, consecutive_failures)
               VALUES (?, ?, 0)
               ON CONFLICT(source) DO UPDATE SET
                   last_success=excluded.last_success,
                   consecutive_failures=0""",
            (source, datetime.utcnow().isoformat()),
        )


def record_feed_error(source: str, error: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO feed_health (source, last_error, consecutive_failures)
               VALUES (?, ?, 1)
               ON CONFLICT(source) DO UPDATE SET
                   last_error=excluded.last_error,
                   consecutive_failures=consecutive_failures+1""",
            (source, str(error)[:500]),
        )


def get_feed_health() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM feed_health ORDER BY consecutive_failures DESC").fetchall()
        return [dict(r) for r in rows]


# ── Tweets ─────────────────────────────────────────────────────────────────

def save_tweet(tweet: dict) -> bool:
    """Insert new tweet or update engagement counts. Returns True if new."""
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM tweets WHERE id=?", (tweet["id"],)).fetchone()
        if existing:
            # Update engagement counts only
            conn.execute(
                "UPDATE tweets SET likes=?, retweets=?, reply_count=? WHERE id=?",
                (tweet.get("likes", 0), tweet.get("retweets", 0), tweet.get("reply_count", 0), tweet["id"]),
            )
            return False
        conn.execute(
            """INSERT INTO tweets
               (id, username, name, text, created_at, url,
                likes, retweets, reply_count, lang, priority_rank, category, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tweet["id"],
                tweet["username"],
                tweet.get("name", ""),
                tweet["text"],
                tweet["created_at"],
                tweet.get("url", ""),
                tweet.get("likes", 0),
                tweet.get("retweets", 0),
                tweet.get("reply_count", 0),
                tweet.get("lang"),
                tweet.get("priority_rank", 2),
                tweet.get("category"),
                datetime.utcnow().isoformat(),
            ),
        )
        return True


# ── Blog posts ─────────────────────────────────────────────────────────────

def update_tweet_translation(tweet_id: str, text_zh: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE tweets SET text_zh=? WHERE id=?",
            (text_zh, tweet_id),
        )


def update_post_translation(post_id: str, title_zh: str, summary_zh: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE blog_posts SET title_zh=?, summary_zh=? WHERE id=?",
            (title_zh, summary_zh, post_id),
        )


def get_untranslated_posts(limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM blog_posts WHERE title_zh IS NULL ORDER BY fetched_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def save_post(post: dict) -> bool:
    """Insert new post. Returns True if new (not a duplicate by id or content_hash)."""
    ch = _content_hash(post["title"])
    with get_conn() as conn:
        # Cross-source dedup: skip if same normalized title already stored
        dup = conn.execute(
            "SELECT id FROM blog_posts WHERE content_hash=?", (ch,)
        ).fetchone()
        if dup:
            return False
        try:
            conn.execute(
                """INSERT INTO blog_posts
                   (id, source, title, url, summary, published, feed_priority, content_hash, category, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    post["id"],
                    post["source"],
                    post["title"],
                    post["url"],
                    post.get("summary", ""),
                    post.get("published", ""),
                    post.get("feed_priority", 2),
                    ch,
                    post.get("category", "ai"),
                    datetime.utcnow().isoformat(),
                ),
            )
            return True
        except sqlite3.IntegrityError:
            return False


# ── Queries ────────────────────────────────────────────────────────────────

def get_latest_tweets(limit: int = 20, username: str = None, category: str = None) -> list[dict]:
    with get_conn() as conn:
        if username:
            rows = conn.execute(
                "SELECT * FROM tweets WHERE username=? ORDER BY created_at DESC LIMIT ?",
                (username, limit),
            ).fetchall()
        elif category:
            rows = conn.execute(
                "SELECT * FROM tweets WHERE category=? ORDER BY created_at DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tweets ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_latest_posts(limit: int = 20, source: str = None) -> list[dict]:
    with get_conn() as conn:
        if source:
            rows = conn.execute(
                "SELECT * FROM blog_posts WHERE source=? ORDER BY published DESC LIMIT ?",
                (source, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM blog_posts ORDER BY published DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_top_tweets(hours: int = 48, limit: int = 10) -> list[dict]:
    cutoff = (datetime.utcnow().timestamp() - hours * 3600)
    from datetime import timezone
    cutoff_iso = datetime.utcfromtimestamp(cutoff).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM tweets
               WHERE created_at >= ?
               ORDER BY (likes + retweets * 2) DESC
               LIMIT ?""",
            (cutoff_iso, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_top_posts(hours: int = 48, limit: int = 10) -> list[dict]:
    cutoff = (datetime.utcnow().timestamp() - hours * 3600)
    cutoff_iso = datetime.utcfromtimestamp(cutoff).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM blog_posts
               WHERE published >= ? OR published IS NULL
               ORDER BY feed_priority ASC, published DESC
               LIMIT ?""",
            (cutoff_iso, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def search_news(query: str, limit: int = 20, source_type: str = "all") -> list[dict]:
    like = f"%{query}%"
    results = []
    with get_conn() as conn:
        if source_type in ("all", "tweets"):
            rows = conn.execute(
                "SELECT *, 'tweet' as item_type FROM tweets WHERE text LIKE ? ORDER BY created_at DESC LIMIT ?",
                (like, limit),
            ).fetchall()
            results.extend([dict(r) for r in rows])
        if source_type in ("all", "posts"):
            rows = conn.execute(
                "SELECT *, 'post' as item_type FROM blog_posts WHERE title LIKE ? OR summary LIKE ? ORDER BY published DESC LIMIT ?",
                (like, like, limit),
            ).fetchall()
            results.extend([dict(r) for r in rows])
    return results[:limit]


# ── Digest send log ────────────────────────────────────────────────────────

def was_digest_sent(date_str: str, hour: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM digest_log WHERE date=? AND hour=?", (date_str, hour)
        ).fetchone()
        return row is not None


def record_digest_sent(date_str: str, hour: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO digest_log (date, hour, sent_at) VALUES (?, ?, ?)",
            (date_str, hour, datetime.utcnow().isoformat()),
        )


def get_recent_posts_by_category(hours: int = 24, limit_per_category: int = 10) -> dict[str, list[dict]]:
    """Return recent posts grouped by category for the daily briefing."""
    cutoff = datetime.utcfromtimestamp(datetime.utcnow().timestamp() - hours * 3600).isoformat()
    categories = ["ai", "web3", "venture", "us_stock", "hk_stock"]
    result = {}
    with get_conn() as conn:
        for cat in categories:
            rows = conn.execute(
                """SELECT * FROM blog_posts
                   WHERE category=? AND (published >= ? OR fetched_at >= ?)
                   ORDER BY published DESC LIMIT ?""",
                (cat, cutoff, cutoff, limit_per_category),
            ).fetchall()
            result[cat] = [dict(r) for r in rows]
    return result


def get_stats() -> dict:
    with get_conn() as conn:
        tweet_count = conn.execute("SELECT COUNT(*) FROM tweets").fetchone()[0]
        post_count  = conn.execute("SELECT COUNT(*) FROM blog_posts").fetchone()[0]
        latest_tweet = conn.execute(
            "SELECT created_at FROM tweets ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        latest_post = conn.execute(
            "SELECT published FROM blog_posts ORDER BY published DESC LIMIT 1"
        ).fetchone()
        return {
            "tweet_count": tweet_count,
            "post_count": post_count,
            "latest_tweet_at": latest_tweet[0] if latest_tweet else None,
            "latest_post_at": latest_post[0] if latest_post else None,
        }
