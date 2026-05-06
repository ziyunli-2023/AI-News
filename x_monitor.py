"""X (Twitter) API v2 monitor — polls user timelines and stores new tweets."""

import logging
import time
import threading
from datetime import datetime, timezone

import tweepy

import config
import storage

logger = logging.getLogger(__name__)


def _build_client() -> tweepy.Client:
    return tweepy.Client(
        bearer_token=config.X_BEARER_TOKEN,
        wait_on_rate_limit=True,
    )


def _resolve_user_ids(client: tweepy.Client, usernames: list[str]) -> dict[str, dict]:
    """Returns {username_lower: {id, name}} map."""
    result = {}
    for i in range(0, len(usernames), 100):
        batch = usernames[i : i + 100]
        resp = client.get_users(usernames=batch, user_fields=["name", "username"])
        if resp.data:
            for u in resp.data:
                result[u.username.lower()] = {"id": str(u.id), "name": u.name}
    return result


def _passes_noise_filter(text: str, priority: int) -> bool:
    """Priority-3 accounts: only save if tweet contains an AI keyword."""
    if priority < 3:
        return True
    text_lower = text.lower()
    return any(kw in text_lower for kw in config.X_NOISE_KEYWORDS)


def _fetch_user_tweets(
    client: tweepy.Client,
    user_id: str,
    username: str,
    name: str,
    priority: int,
    category: str,
    since_id: str = None,
) -> list[dict]:
    """Fetch recent tweets for a single user."""
    kwargs = dict(
        id=user_id,
        max_results=10,
        tweet_fields=["created_at", "public_metrics", "text", "lang"],
        exclude=["retweets", "replies"],
    )
    if since_id:
        kwargs["since_id"] = since_id

    try:
        resp = client.get_users_tweets(**kwargs)
    except tweepy.TooManyRequests:
        logger.warning("Rate limit hit for @%s, skipping this cycle", username)
        return []
    except tweepy.TwitterServerError as e:
        logger.error("Twitter server error for @%s: %s", username, e)
        return []

    if not resp.data:
        return []

    tweets = []
    for t in resp.data:
        # Language filter: skip non-English (lang may be None for some tweets)
        lang = getattr(t, "lang", None)
        if lang and lang not in ("en", "und"):
            continue

        # Noise filter for priority-3 accounts
        if not _passes_noise_filter(t.text, priority):
            continue

        metrics = t.public_metrics or {}
        tweets.append(
            {
                "id": str(t.id),
                "username": username,
                "name": name,
                "text": t.text,
                "created_at": t.created_at.isoformat() if t.created_at else datetime.now(timezone.utc).isoformat(),
                "url": f"https://x.com/{username}/status/{t.id}",
                "likes": metrics.get("like_count", 0),
                "retweets": metrics.get("retweet_count", 0),
                "reply_count": metrics.get("reply_count", 0),
                "lang": lang,
                "priority_rank": priority,
                "category": category,
            }
        )
    return tweets


class XMonitor:
    def __init__(self, on_new_tweet=None):
        self._on_new_tweet = on_new_tweet  # callback(tweet_dict)
        self._stop = threading.Event()
        self._thread = None
        self._since_ids: dict[str, str] = {}  # {user_id: since_id}
        self.last_poll_at: str = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="x-monitor")
        self._thread.start()
        logger.info("X monitor started (%d accounts, Free tier)", len(config.TRACKED_X_USERS))

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("X monitor stopped")

    def _run(self):
        if not config.X_BEARER_TOKEN:
            logger.warning("X_BEARER_TOKEN not set — X monitor disabled")
            return

        client = _build_client()

        # Load persisted cursors from DB
        self._since_ids = storage.load_cursors()
        logger.info("Loaded %d cursors from DB", len(self._since_ids))

        usernames = [u["username"] for u in config.TRACKED_X_USERS]
        user_meta = {u["username"].lower(): u for u in config.TRACKED_X_USERS}

        logger.info("Resolving user IDs for %d accounts…", len(usernames))
        try:
            user_map = _resolve_user_ids(client, usernames)
        except Exception as e:
            logger.error("Failed to resolve user IDs: %s", e)
            return
        logger.info("Resolved %d / %d users", len(user_map), len(usernames))

        while not self._stop.is_set():
            new_count = 0
            for username_lower, info in user_map.items():
                if self._stop.is_set():
                    break
                meta = user_meta.get(username_lower, {})
                tweets = _fetch_user_tweets(
                    client,
                    user_id=info["id"],
                    username=username_lower,
                    name=info["name"],
                    priority=meta.get("priority", 2),
                    category=meta.get("category", ""),
                    since_id=self._since_ids.get(info["id"]),
                )
                for tweet in tweets:
                    is_new = storage.save_tweet(tweet)
                    if is_new:
                        new_count += 1
                        if self._on_new_tweet:
                            self._on_new_tweet(tweet)
                        logger.debug("New tweet @%s: %s…", tweet["username"], tweet["text"][:60])
                    # Persist highest seen ID
                    if info["id"] not in self._since_ids or tweet["id"] > self._since_ids[info["id"]]:
                        self._since_ids[info["id"]] = tweet["id"]
                        storage.save_cursor(info["id"], username_lower, tweet["id"])

                time.sleep(2)  # polite delay between users

            self.last_poll_at = datetime.utcnow().isoformat()
            if new_count:
                logger.info("X: %d new tweet(s) this cycle", new_count)
            else:
                logger.debug("X: no new tweets this cycle")

            self._stop.wait(config.X_POLL_INTERVAL)
