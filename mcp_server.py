"""MCP server — exposes AI news tools to Claude Code."""

import asyncio
import logging
import threading
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

import config
import storage
from x_monitor import XMonitor
from rss_monitor import RSSMonitor

logger = logging.getLogger(__name__)

# ── New-item cache (cleared on get_new_since_last_check) ──────────────────
_new_tweets: list[dict] = []
_new_posts: list[dict] = []
_cache_lock = threading.Lock()

# Monitor references (set in main, read by health tool)
_x_mon: XMonitor = None
_rss_mon: RSSMonitor = None


def _on_new_tweet(tweet: dict):
    with _cache_lock:
        _new_tweets.append(tweet)
        if len(_new_tweets) > 200:
            _new_tweets.pop(0)


def _on_new_post(post: dict):
    with _cache_lock:
        _new_posts.append(post)
        if len(_new_posts) > 200:
            _new_posts.pop(0)


# ── Helpers ────────────────────────────────────────────────────────────────

def _fmt_tweet(t: dict) -> str:
    return (
        f"🐦 @{t['username']}  {t['created_at'][:16]}"
        + (f"  [{t['category']}]" if t.get("category") else "")
        + f"\n{t['text']}\n"
        f"❤ {t['likes']}  🔁 {t['retweets']}  💬 {t.get('reply_count', 0)}\n"
        f"{t.get('url', '')}"
    )


def _fmt_post(p: dict) -> str:
    date = p.get("published", "")[:16] if p.get("published") else "unknown"
    lines = [f"📰 [{p['source']}]  {date}\n{p['title']}\n{p['url']}"]
    if p.get("summary"):
        lines.append(p["summary"][:200] + ("…" if len(p.get("summary","")) > 200 else ""))
    return "\n".join(lines)


def _fmt_paper(p: dict) -> str:
    """Format a paper row with score/upvotes/authors."""
    import json as _json
    score = float(p.get("paper_score") or 0)
    uv    = int(p.get("hf_upvotes")   or 0)
    hn    = int(p.get("hn_score")     or 0)
    arxiv = p.get("arxiv_id") or ""
    pdf   = p.get("pdf_url")  or ""
    date  = (p.get("published") or "")[:10]

    badges = [f"score={score:.1f}"]
    if uv:    badges.append(f"👍{uv}")
    if hn:    badges.append(f"HN={hn}")
    if arxiv: badges.append(f"arXiv:{arxiv}")
    head = "📄 [{src}]  {date}  ({tags})".format(
        src=p.get("source") or "", date=date, tags=" · ".join(badges),
    )

    lines = [head, p.get("title") or ""]
    if p.get("title_zh"):
        lines.append(f"   {p['title_zh']}")
    try:
        authors = _json.loads(p.get("authors") or "[]")
        if isinstance(authors, list) and authors:
            head_authors = ", ".join(authors[:3])
            tail = f" +{len(authors) - 3}" if len(authors) > 3 else ""
            lines.append(f"👥 {head_authors}{tail}")
    except Exception:
        pass

    if p.get("url"):
        lines.append(p["url"])
    if pdf and pdf != p.get("url"):
        lines.append(f"PDF: {pdf}")
    if p.get("summary"):
        s = p["summary"]
        lines.append(s[:240] + ("…" if len(s) > 240 else ""))
    return "\n".join(lines)


# ── MCP server ─────────────────────────────────────────────────────────────
app = Server("ai-news-monitor")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_latest_tweets",
            description="Get the latest tweets from tracked AI influencers, ordered by date.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit":    {"type": "integer", "default": 20, "description": "Max items (default 20, max 100)"},
                    "username": {"type": "string",  "description": "Filter by X username (optional)"},
                },
            },
        ),
        types.Tool(
            name="get_latest_blog_posts",
            description="Get the latest posts from tracked AI blogs and newsletters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit":  {"type": "integer", "default": 20, "description": "Max items (default 20, max 100)"},
                    "source": {"type": "string",  "description": "Filter by source name, e.g. 'OpenAI' (optional)"},
                },
            },
        ),
        types.Tool(
            name="get_all_news",
            description="Combined feed of latest tweets + blog posts, sorted by date.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 30, "description": "Total items (default 30)"},
                },
            },
        ),
        types.Tool(
            name="get_new_since_last_check",
            description="Get only items that arrived since the last call to this tool. Call periodically for real-time updates.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_top_posts",
            description="Get highest-engagement tweets and highest-priority blog posts from the last N hours.",
            inputSchema={
                "type": "object",
                "properties": {
                    "hours":  {"type": "integer", "default": 48, "description": "Look-back window in hours (default 48)"},
                    "limit":  {"type": "integer", "default": 10, "description": "Items per source type (default 10)"},
                },
            },
        ),
        types.Tool(
            name="search_news",
            description="Full-text search across tweets and blog posts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query":       {"type": "string",  "description": "Search term"},
                    "limit":       {"type": "integer", "default": 20, "description": "Max results (default 20)"},
                    "source_type": {"type": "string",  "default": "all", "description": "'tweets', 'posts', or 'all'"},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_by_category",
            description="Get recent tweets filtered by account category.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "One of: researcher, founder, safety, academic, practitioner"},
                    "limit":    {"type": "integer", "default": 20},
                },
                "required": ["category"],
            },
        ),
        types.Tool(
            name="get_health",
            description="Show monitor health: last poll times, failed feeds, DB stats.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_stats",
            description="Database statistics: total tweets, posts, latest timestamps.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="list_tracked_sources",
            description="List all tracked X accounts and RSS feeds.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_trending_papers",
            description=(
                "Get trending AI papers ranked by paper_score. The score blends "
                "tier (大模型公司技术报告 +15, 顶级实验室 +5), HF Daily Papers "
                "upvotes, HN discussion, and recency. Use this to surface the "
                "most-discussed and most-technical recent work."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "hours":      {"type": "integer", "default": 72,  "description": "Look-back window in hours (default 72)"},
                    "limit":      {"type": "integer", "default": 10,  "description": "Max papers to return (default 10, max 50)"},
                    "min_score":  {"type": "number",  "default": 0.0, "description": "Minimum paper_score (default 0)"},
                },
            },
        ),
        types.Tool(
            name="get_papers_by_lab",
            description=(
                "Get papers from a specific AI lab or model company by source-name "
                "substring match. Examples: 'DeepSeek', 'Qwen', 'Apple', 'AI2', "
                "'字节', '智谱', 'Moonshot'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "lab":   {"type": "string",  "description": "Lab name substring (matches against the source field)"},
                    "limit": {"type": "integer", "default": 20, "description": "Max papers to return (default 20, max 100)"},
                },
                "required": ["lab"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:

    # ── get_latest_tweets ──────────────────────────────────────────────────
    if name == "get_latest_tweets":
        limit    = min(int(arguments.get("limit", 20)), 100)
        username = arguments.get("username")
        tweets   = storage.get_latest_tweets(limit=limit, username=username)
        if not tweets:
            return [types.TextContent(type="text", text="No tweets yet — monitor may still be starting up.")]
        return [types.TextContent(type="text", text="\n\n---\n\n".join(_fmt_tweet(t) for t in tweets))]

    # ── get_latest_blog_posts ──────────────────────────────────────────────
    elif name == "get_latest_blog_posts":
        limit  = min(int(arguments.get("limit", 20)), 100)
        source = arguments.get("source")
        posts  = storage.get_latest_posts(limit=limit, source=source)
        if not posts:
            return [types.TextContent(type="text", text="No blog posts yet.")]
        return [types.TextContent(type="text", text="\n\n---\n\n".join(_fmt_post(p) for p in posts))]

    # ── get_all_news ───────────────────────────────────────────────────────
    elif name == "get_all_news":
        limit  = min(int(arguments.get("limit", 30)), 200)
        fetch  = limit * 2  # fetch more from each, then merge & truncate
        tweets = storage.get_latest_tweets(limit=fetch)
        posts  = storage.get_latest_posts(limit=fetch)

        items = []
        for t in tweets:
            items.append({"type": "tweet", "date": t["created_at"], "data": t})
        for p in posts:
            items.append({"type": "post",  "date": p.get("published", ""), "data": p})

        items.sort(key=lambda x: x["date"], reverse=True)
        items = items[:limit]

        if not items:
            return [types.TextContent(type="text", text="No news yet — monitors are starting up.")]

        parts = []
        for item in items:
            parts.append(_fmt_tweet(item["data"]) if item["type"] == "tweet" else _fmt_post(item["data"]))
        return [types.TextContent(type="text", text="\n\n---\n\n".join(parts))]

    # ── get_new_since_last_check ───────────────────────────────────────────
    elif name == "get_new_since_last_check":
        with _cache_lock:
            tweets = list(_new_tweets)
            posts  = list(_new_posts)
            _new_tweets.clear()
            _new_posts.clear()

        if not tweets and not posts:
            return [types.TextContent(type="text", text="No new items since last check.")]

        parts = []
        if tweets:
            parts.append(f"## {len(tweets)} new tweet(s)\n")
            parts.extend(_fmt_tweet(t) for t in tweets)
        if posts:
            parts.append(f"## {len(posts)} new blog post(s)\n")
            parts.extend(_fmt_post(p) for p in posts)
        return [types.TextContent(type="text", text="\n\n---\n\n".join(parts))]

    # ── get_top_posts ──────────────────────────────────────────────────────
    elif name == "get_top_posts":
        hours = int(arguments.get("hours", 48))
        limit = min(int(arguments.get("limit", 10)), 50)
        tweets = storage.get_top_tweets(hours=hours, limit=limit)
        posts  = storage.get_top_posts(hours=hours, limit=limit)

        parts = []
        if tweets:
            parts.append(f"## Top tweets (last {hours}h by engagement)")
            parts.extend(_fmt_tweet(t) for t in tweets)
        if posts:
            parts.append(f"## Top blog posts (last {hours}h by priority)")
            parts.extend(_fmt_post(p) for p in posts)
        if not parts:
            return [types.TextContent(type="text", text=f"No items found in the last {hours} hours.")]
        return [types.TextContent(type="text", text="\n\n---\n\n".join(parts))]

    # ── search_news ────────────────────────────────────────────────────────
    elif name == "search_news":
        query       = arguments.get("query", "")
        limit       = min(int(arguments.get("limit", 20)), 100)
        source_type = arguments.get("source_type", "all")
        if not query:
            return [types.TextContent(type="text", text="Please provide a search query.")]

        results = storage.search_news(query=query, limit=limit, source_type=source_type)
        if not results:
            return [types.TextContent(type="text", text=f"No results for '{query}'.")]

        parts = []
        for r in results:
            if r.get("item_type") == "tweet" or "text" in r:
                parts.append(_fmt_tweet(r))
            else:
                parts.append(_fmt_post(r))
        return [types.TextContent(type="text", text="\n\n---\n\n".join(parts))]

    # ── get_by_category ────────────────────────────────────────────────────
    elif name == "get_by_category":
        category = arguments.get("category", "")
        limit    = min(int(arguments.get("limit", 20)), 100)
        tweets   = storage.get_latest_tweets(limit=limit, category=category)
        if not tweets:
            return [types.TextContent(type="text", text=f"No tweets found for category '{category}'.")]
        return [types.TextContent(type="text", text="\n\n---\n\n".join(_fmt_tweet(t) for t in tweets))]

    # ── get_health ─────────────────────────────────────────────────────────
    elif name == "get_health":
        stats  = storage.get_stats()
        health = storage.get_feed_health()
        failed = [h for h in health if h["consecutive_failures"] > 0]

        x_last  = _x_mon.last_poll_at  if _x_mon  else "not started"
        rss_last = _rss_mon.last_poll_at if _rss_mon else "not started"

        lines = [
            "## Monitor Health",
            f"  X monitor last polled : {x_last or 'pending first cycle'}",
            f"  RSS monitor last polled: {rss_last or 'pending first cycle'}",
            f"  Tweets in DB : {stats['tweet_count']}",
            f"  Posts in DB  : {stats['post_count']}",
        ]
        if failed:
            lines.append(f"\n## Failing feeds ({len(failed)})")
            for h in failed:
                lines.append(f"  ✗ {h['source']} — {h['consecutive_failures']} failure(s): {h['last_error']}")
        else:
            lines.append("\n✓ All feeds healthy")

        return [types.TextContent(type="text", text="\n".join(lines))]

    # ── get_stats ──────────────────────────────────────────────────────────
    elif name == "get_stats":
        s = storage.get_stats()
        text = (
            f"Tweets  : {s['tweet_count']}\n"
            f"Posts   : {s['post_count']}\n"
            f"Latest tweet : {s['latest_tweet_at'] or 'none'}\n"
            f"Latest post  : {s['latest_post_at'] or 'none'}"
        )
        return [types.TextContent(type="text", text=text)]

    # ── get_trending_papers ────────────────────────────────────────────────
    elif name == "get_trending_papers":
        hours     = int(arguments.get("hours", 72))
        limit     = min(int(arguments.get("limit", 10)), 50)
        min_score = float(arguments.get("min_score", 0.0))
        papers    = storage.get_trending_papers(hours=hours, limit=limit, min_score=min_score)
        if not papers:
            return [types.TextContent(
                type="text",
                text=f"No trending papers in the last {hours}h (min_score={min_score}).",
            )]
        header = (f"## 🔥 Trending papers (last {hours}h, top {len(papers)} by paper_score)\n"
                  f"Tier weighting: 大模型公司 +15 · 顶级实验室 +5 · HF upvotes (log) · HN (log) · recency.\n")
        body = "\n\n---\n\n".join(_fmt_paper(p) for p in papers)
        return [types.TextContent(type="text", text=header + "\n" + body)]

    # ── get_papers_by_lab ──────────────────────────────────────────────────
    elif name == "get_papers_by_lab":
        lab   = arguments.get("lab", "").strip()
        limit = min(int(arguments.get("limit", 20)), 100)
        if not lab:
            return [types.TextContent(type="text", text="Please specify a lab name.")]
        papers = storage.get_papers_by_lab(lab_label=lab, limit=limit)
        if not papers:
            return [types.TextContent(
                type="text",
                text=f"No papers found with source matching '{lab}'. "
                     f"Try names like 'DeepSeek', 'Qwen', 'Apple', 'AI2', '字节', '智谱'.",
            )]
        header = f"## 📄 Papers from {lab} ({len(papers)} found)\n"
        body = "\n\n---\n\n".join(_fmt_paper(p) for p in papers)
        return [types.TextContent(type="text", text=header + "\n" + body)]

    # ── list_tracked_sources ───────────────────────────────────────────────
    elif name == "list_tracked_sources":
        x_list   = "\n".join(
            f"  @{u['username']} [{u['category']}] P{u['priority']}"
            for u in config.TRACKED_X_USERS
        )
        rss_list = "\n".join(
            f"  [T{f['tier']}] {f['name']}"
            for f in config.RSS_FEEDS
        )
        text = (
            f"## X accounts tracked ({len(config.TRACKED_X_USERS)}) — Free tier\n{x_list}\n\n"
            f"## RSS feeds ({len(config.RSS_FEEDS)})\n{rss_list}"
        )
        return [types.TextContent(type="text", text=text)]

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


# ── Entry point ────────────────────────────────────────────────────────────

async def main():
    global _x_mon, _rss_mon

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    storage.init_db()
    logger.info("Database initialised")

    _x_mon   = None  # X API requires Basic tier ($100/mo) to read timelines
    _rss_mon = RSSMonitor(on_new_post=_on_new_post)
    _rss_mon.start()

    logger.info("Starting MCP server via stdio…")
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())
    finally:
        _rss_mon.stop()


if __name__ == "__main__":
    asyncio.run(main())
