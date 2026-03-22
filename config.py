"""Configuration: tracked X accounts, RSS feeds, and API settings."""

import os
from dotenv import load_dotenv

load_dotenv()

# ── X API credentials ──────────────────────────────────────────────────────
# Only Bearer Token is needed for reading public timelines (app-only auth)
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")

# ── Polling intervals ──────────────────────────────────────────────────────
# Free tier: 1 req/15min app-wide. 8 users × 1 req = 8 reqs per cycle.
# At 1800s interval: 8 reqs/30min = comfortably within free limits.
X_POLL_INTERVAL = 1800  # 30 min

# RSS tiered intervals (seconds) by tier level
RSS_POLL_INTERVALS = {1: 1800, 2: 3600, 3: 7200}

# ── Tracked X accounts ─────────────────────────────────────────────────────
# Each entry: username, priority (1/2/3), category
# NOTE: X monitor requires Basic tier ($100/mo). Active accounts listed here
# are ready to enable once API access is upgraded.
TRACKED_X_USERS = [
    # ── AI 圈 行业领袖 ──────────────────────────────────────────────────────
    {"username": "sama",           "priority": 1, "category": "founder"},     # Sam Altman
    {"username": "DarioAmodei",    "priority": 1, "category": "founder"},     # Dario Amodei
    {"username": "demishassabis",  "priority": 1, "category": "founder"},     # Demis Hassabis
    {"username": "ylecun",         "priority": 1, "category": "researcher"},  # Yann LeCun
    {"username": "AndrewYNg",      "priority": 1, "category": "academic"},    # Andrew Ng
    # ── AI 圈 开源/教育 ─────────────────────────────────────────────────────
    {"username": "karpathy",       "priority": 1, "category": "researcher"},  # Andrej Karpathy
    {"username": "jeremyphoward",  "priority": 2, "category": "academic"},    # Jeremy Howard
    # ── AI 圈 投资人 ────────────────────────────────────────────────────────
    {"username": "paulg",          "priority": 2, "category": "investor"},    # Paul Graham
    {"username": "eladgil",        "priority": 2, "category": "investor"},    # Elad Gil
    {"username": "garrytan",       "priority": 2, "category": "investor"},    # Garry Tan
    # ── Web3 圈 行业领袖 ────────────────────────────────────────────────────
    {"username": "VitalikButerin", "priority": 1, "category": "web3"},        # Vitalik Buterin
    {"username": "brian_armstrong","priority": 2, "category": "web3"},        # Brian Armstrong
    {"username": "cz_binance",     "priority": 2, "category": "web3"},        # CZ
    # ── Web3 圈 技术开发者 ──────────────────────────────────────────────────
    {"username": "haydenzadams",   "priority": 2, "category": "web3"},        # Hayden Adams (Uniswap)
    {"username": "AndreCronjeTech","priority": 2, "category": "web3"},        # Andre Cronje
    {"username": "StaniKulechov",  "priority": 2, "category": "web3"},        # Stani Kulechov (Aave)
    # ── Web3 圈 投资人 ──────────────────────────────────────────────────────
    {"username": "cdixon",         "priority": 2, "category": "web3"},        # Chris Dixon (a16z)
    {"username": "naval",          "priority": 2, "category": "web3"},        # Naval Ravikant
    {"username": "balajis",        "priority": 2, "category": "web3"},        # Balaji Srinivasan
    {"username": "fehrsam",        "priority": 2, "category": "web3"},        # Fred Ehrsam (Paradigm)
    # ── Web3 圈 KOL/媒体 ────────────────────────────────────────────────────
    {"username": "RyanSAdams",     "priority": 3, "category": "web3"},        # Ryan Sean Adams (Bankless)
    {"username": "TrustlessState", "priority": 3, "category": "web3"},        # David Hoffman (Bankless)
    {"username": "sassal0x",       "priority": 3, "category": "web3"},        # Anthony Sassano
    {"username": "laurashin",      "priority": 3, "category": "web3"},        # Laura Shin
]

# Keywords used to filter Priority-3 accounts (only save if tweet contains one)
X_NOISE_KEYWORDS = {
    "llm", "gpt", "claude", "gemini", "model", "paper", "research",
    "alignment", "safety", "agent", "benchmark", "rlhf", "training",
    "inference", "transformer", "multimodal", "reasoning", "openai",
    "anthropic", "deepmind", "mistral", "llama", "neural", "dataset",
}

# ── RSS feeds ──────────────────────────────────────────────────────────────
# Each entry: name, url, tier (1/2/3), is_arxiv (optional)
RSS_FEEDS = [
    # ── AI — Personal blogs (Tier 1, poll every 30 min) ────────────────────
    {"name": "Sam Altman",         "url": "https://blog.samaltman.com/posts.atom",                                                             "tier": 1, "category": "ai"},
    {"name": "Paul Graham",        "url": "https://paulgraham.com/rss.html",                                                                   "tier": 1, "category": "ai"},
    # ── AI — Lab blogs + deep newsletters (Tier 1, poll every 30 min) ──────
    {"name": "OpenAI",             "url": "https://openai.com/news/rss.xml",                                                                   "tier": 1, "category": "ai"},
    {"name": "Anthropic",          "url": "https://raw.githubusercontent.com/0xSMW/rss-feeds/main/feeds/feed_anthropic_news.xml",              "tier": 1, "category": "ai"},
    {"name": "Google DeepMind",    "url": "https://deepmind.google/blog/rss.xml",                                                              "tier": 1, "category": "ai"},
    {"name": "Meta AI",            "url": "https://ai.meta.com/blog/rss/",                                                                     "tier": 1, "category": "ai"},
    {"name": "Hugging Face",       "url": "https://huggingface.co/blog/feed.xml",                                                              "tier": 1, "category": "ai"},
    {"name": "Import AI",          "url": "https://importai.substack.com/feed",                                                                "tier": 1, "category": "ai"},
    {"name": "Interconnects",      "url": "https://www.interconnects.ai/feed",                                                                 "tier": 1, "category": "ai"},
    {"name": "Ahead of AI",        "url": "https://magazine.sebastianraschka.com/feed",                                                        "tier": 1, "category": "ai"},
    {"name": "The Batch",          "url": "https://www.deeplearning.ai/the-batch/feed.xml",                                                    "tier": 1, "category": "ai"},
    # ── AI — Research & industry blogs (Tier 2, poll every 60 min) ─────────
    {"name": "Google AI",          "url": "https://blog.google/technology/ai/rss/",                                                            "tier": 2, "category": "ai"},
    {"name": "Google Research",    "url": "https://research.google/blog/rss/",                                                                 "tier": 2, "category": "ai"},
    {"name": "AWS ML",             "url": "https://aws.amazon.com/blogs/machine-learning/feed/",                                               "tier": 2, "category": "ai"},
    {"name": "BAIR",               "url": "https://bair.berkeley.edu/blog/feed.xml",                                                           "tier": 2, "category": "ai"},
    {"name": "Last Week in AI",    "url": "https://lastweekin.ai/feed",                                                                        "tier": 2, "category": "ai"},
    {"name": "Marcus on AI",       "url": "https://garymarcus.substack.com/feed",                                                              "tier": 2, "category": "ai"},
    {"name": "Chollet Substack",   "url": "https://fchollet.substack.com/feed",                                                                "tier": 2, "category": "ai"},
    {"name": "The Decoder",        "url": "https://the-decoder.com/feed/",                                                                     "tier": 2, "category": "ai"},
    # ── AI — High-volume news sites (Tier 3, poll every 2 hr) ───────────────
    {"name": "VentureBeat AI",     "url": "https://venturebeat.com/category/ai/feed/",                                                         "tier": 3, "category": "ai"},
    {"name": "The Verge AI",       "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",                                 "tier": 3, "category": "ai"},
    {"name": "Wired AI",           "url": "https://www.wired.com/feed/tag/ai/latest/rss",                                                      "tier": 3, "category": "ai"},
    {"name": "Towards Data Science","url": "https://towardsdatascience.com/feed/",                                                             "tier": 3, "category": "ai"},
    # ── AI — ArXiv (keyword-filtered) ───────────────────────────────────────
    {"name": "arXiv cs.AI",        "url": "http://arxiv.org/rss/cs.AI",  "tier": 2, "category": "ai", "is_arxiv": True},
    {"name": "arXiv cs.LG",        "url": "http://arxiv.org/rss/cs.LG",  "tier": 2, "category": "ai", "is_arxiv": True},

    # ── Web3 / Crypto (poll every 60 min) ───────────────────────────────────
    {"name": "CoinDesk",           "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",                                                   "tier": 2, "category": "web3"},
    {"name": "CoinTelegraph",      "url": "https://cointelegraph.com/rss",                                                                     "tier": 2, "category": "web3"},
    {"name": "The Block",          "url": "https://www.theblock.co/rss.xml",                                                                   "tier": 2, "category": "web3"},
    {"name": "Decrypt",            "url": "https://decrypt.co/feed",                                                                           "tier": 2, "category": "web3"},

    # ── 创投圈 / Venture (poll every 60 min) ─────────────────────────────────
    {"name": "Y Combinator",       "url": "https://www.ycombinator.com/blog/rss.xml",                                                          "tier": 1, "category": "venture"},
    {"name": "a16z",               "url": "https://a16z.com/feed/",                                                                            "tier": 1, "category": "venture"},
    {"name": "TechCrunch",         "url": "https://techcrunch.com/feed/",                                                                      "tier": 2, "category": "venture"},
    {"name": "Crunchbase News",    "url": "https://news.crunchbase.com/feed/",                                                                 "tier": 2, "category": "venture"},
    {"name": "StrictlyVC",         "url": "https://strictlyvc.com/feed/",                                                                      "tier": 2, "category": "venture"},

    # ── 美股 / US Stocks (poll every 60 min) ────────────────────────────────
    {"name": "MarketWatch",        "url": "https://feeds.marketwatch.com/marketwatch/topstories/",                                             "tier": 2, "category": "us_stock"},
    {"name": "CNBC Markets",       "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html",                                              "tier": 2, "category": "us_stock"},
    {"name": "Reuters Business",   "url": "https://feeds.reuters.com/reuters/businessNews",                                                    "tier": 2, "category": "us_stock"},

    # ── Web3 圈官方博客 (poll every 60 min) ─────────────────────────────────
    {"name": "a16z Crypto",        "url": "https://a16zcrypto.com/feed/",                                                                      "tier": 1, "category": "web3"},
    {"name": "Paradigm",           "url": "https://www.paradigm.xyz/feed.xml",                                                                 "tier": 2, "category": "web3"},
    {"name": "CoinCenter",         "url": "https://coincenter.org/feed",                                                                       "tier": 2, "category": "web3"},
]

# Keywords for ArXiv filtering (only store papers matching at least one)
ARXIV_KEYWORDS = {
    "language model", "large language", "llm", "alignment", "reasoning",
    "agent", "rlhf", "multimodal", "instruction tuning", "chain-of-thought",
    "in-context learning", "fine-tuning", "reinforcement learning from human",
    "vision-language", "text-to-image", "diffusion model", "transformer",
    "retrieval-augmented", "hallucination", "jailbreak", "safety",
}

# ── DeepSeek API ──────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# ── Storage ────────────────────────────────────────────────────────────────
DB_PATH = "news.db"

# ── Email notifications (Gmail SMTP) ───────────────────────────────────────
EMAIL_SENDER       = os.getenv("EMAIL_SENDER", "")        # your Gmail address
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")  # Gmail App Password
EMAIL_RECIPIENT    = os.getenv("EMAIL_RECIPIENT", "")     # where to receive

# ── Web dashboard ──────────────────────────────────────────────────────────
WEB_PORT = int(os.getenv("WEB_PORT", "8000"))
