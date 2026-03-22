"""Standalone entry point — runs RSS monitor + web server + email notifier + translator."""

import asyncio
import logging
import threading

import uvicorn

import config
import storage
import ai_processor
from rss_monitor import RSSMonitor
from nitter_monitor import NitterMonitor
from notifier import EmailNotifier
from web_server import app, push_new_item

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


def make_callbacks(notifier: EmailNotifier):
    def on_new_post(post: dict):
        notifier.enqueue(post, "post")
        asyncio.run_coroutine_threadsafe(
            push_new_item(post, "post"), _loop
        )

    def on_new_tweet(tweet: dict):
        notifier.enqueue(tweet, "tweet")
        asyncio.run_coroutine_threadsafe(
            push_new_item(tweet, "tweet"), _loop
        )

    return on_new_post, on_new_tweet


def start_translation_worker(stop_event: threading.Event):
    """Background thread: every 5 min, translate untranslated posts in batches of 5."""
    if not config.DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY not set — translation worker disabled")
        return

    def _run():
        logger.info("Translation worker started")
        while not stop_event.is_set():
            posts = storage.get_untranslated_posts(limit=10)
            if posts:
                # Process in chunks of 5
                for i in range(0, len(posts), 5):
                    chunk = posts[i:i+5]
                    results = ai_processor.translate_batch(chunk)
                    for post, result in zip(chunk, results):
                        if result.get("title_zh"):
                            storage.update_post_translation(
                                post["id"],
                                result["title_zh"],
                                result.get("summary_zh", ""),
                            )
                    if stop_event.is_set():
                        break
                logger.info("Translation worker: translated %d post(s)", len(posts))
            stop_event.wait(300)  # 5 minutes

    t = threading.Thread(target=_run, daemon=True, name="translation-worker")
    t.start()
    return t


async def main():
    global _loop
    _loop = asyncio.get_event_loop()

    storage.init_db()
    logger.info("Database initialised")

    notifier = EmailNotifier()
    notifier.start()

    on_new_post, on_new_tweet = make_callbacks(notifier)

    rss_mon = RSSMonitor(on_new_post=on_new_post)
    rss_mon.start()

    nitter_mon = NitterMonitor(on_new_tweet=on_new_tweet)
    nitter_mon.start()

    stop_event = threading.Event()
    start_translation_worker(stop_event)

    logger.info("Web dashboard → http://0.0.0.0:%d", config.WEB_PORT)

    server_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=config.WEB_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(server_config)

    try:
        await server.serve()
    finally:
        rss_mon.stop()
        nitter_mon.stop()
        notifier.stop()
        stop_event.set()


_loop = None

if __name__ == "__main__":
    asyncio.run(main())
