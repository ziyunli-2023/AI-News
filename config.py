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

# ── Tracked X accounts (Free tier: Priority 1 only = 8 accounts) ──────────
# Each entry: username, priority (1/2/3), category
TRACKED_X_USERS = [
    {"username": "karpathy",    "priority": 1, "category": "researcher"},  # Andrej Karpathy
    {"username": "DarioAmodei", "priority": 1, "category": "founder"},     # Dario Amodei
    {"username": "sama",        "priority": 1, "category": "founder"},     # Sam Altman
    {"username": "ilyasut",     "priority": 1, "category": "researcher"},  # Ilya Sutskever
    {"username": "fchollet",    "priority": 1, "category": "researcher"},  # François Chollet
    {"username": "ch402",       "priority": 1, "category": "researcher"},  # Chris Olah
    {"username": "Thom_Wolf",   "priority": 1, "category": "researcher"},  # Thomas Wolf
    {"username": "natolambert", "priority": 1, "category": "researcher"},  # Nathan Lambert
    # ── Upgrade to Basic tier ($100/mo) to enable the accounts below ──────
    # {"username": "demishassabis",  "priority": 2, "category": "founder"},
    # {"username": "gdb",            "priority": 2, "category": "founder"},
    # {"username": "AravSrinivas",   "priority": 2, "category": "founder"},
    # {"username": "JeffDean",       "priority": 2, "category": "researcher"},
    # {"username": "soumithchintala","priority": 2, "category": "researcher"},
    # {"username": "DrJimFan",       "priority": 2, "category": "researcher"},
    # {"username": "jackclarkSF",    "priority": 2, "category": "researcher"},
    # {"username": "OfficialLoganK", "priority": 2, "category": "practitioner"},
    # {"username": "paulfchristiano","priority": 2, "category": "safety"},
    # {"username": "tegmark",        "priority": 2, "category": "safety"},
    # {"username": "AndrewYNg",      "priority": 2, "category": "academic"},
    # {"username": "drfeifei",       "priority": 2, "category": "academic"},
    # {"username": "rasbt",          "priority": 2, "category": "academic"},
    # {"username": "emollick",       "priority": 2, "category": "academic"},
    # {"username": "chipro",         "priority": 2, "category": "practitioner"},
    # {"username": "alliekmiller",   "priority": 2, "category": "practitioner"},
    # {"username": "lexfridman",     "priority": 2, "category": "practitioner"},
    # {"username": "ylecun",         "priority": 3, "category": "researcher"},
    # {"username": "GaryMarcus",     "priority": 3, "category": "academic"},
    # {"username": "ESYudkowsky",    "priority": 3, "category": "safety"},
    # {"username": "rowancheung",    "priority": 3, "category": "practitioner"},
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
    # Tier 1 — Lab blogs + deep newsletters (poll every 30 min)
    {"name": "OpenAI",        "url": "https://openai.com/news/rss.xml",                                                                    "tier": 1},
    {"name": "Anthropic",     "url": "https://raw.githubusercontent.com/0xSMW/rss-feeds/main/feeds/feed_anthropic_news.xml",               "tier": 1},
    {"name": "Google DeepMind","url": "https://deepmind.google/blog/rss.xml",                                                              "tier": 1},
    {"name": "Hugging Face",  "url": "https://huggingface.co/blog/feed.xml",                                                               "tier": 1},
    {"name": "Import AI",     "url": "https://importai.substack.com/feed",                                                                 "tier": 1},
    {"name": "Interconnects", "url": "https://www.interconnects.ai/feed",                                                                  "tier": 1},
    {"name": "Ahead of AI",   "url": "https://magazine.sebastianraschka.com/feed",                                                         "tier": 1},
    {"name": "The Batch",     "url": "https://www.deeplearning.ai/the-batch/feed.xml",                                                     "tier": 1},
    # Tier 2 — Research & industry blogs (poll every 60 min)
    {"name": "Google AI",     "url": "https://blog.google/technology/ai/rss/",                                                             "tier": 2},
    {"name": "Google Research","url": "https://research.google/blog/rss/",                                                                 "tier": 2},
    {"name": "AWS ML",        "url": "https://aws.amazon.com/blogs/machine-learning/feed/",                                                "tier": 2},
    {"name": "BAIR",          "url": "https://bair.berkeley.edu/blog/feed.xml",                                                            "tier": 2},
    {"name": "Last Week in AI","url": "https://lastweekin.ai/feed",                                                                        "tier": 2},
    {"name": "Marcus on AI",  "url": "https://garymarcus.substack.com/feed",                                                               "tier": 2},
    {"name": "Chollet Substack","url": "https://fchollet.substack.com/feed",                                                               "tier": 2},
    {"name": "The Decoder",   "url": "https://the-decoder.com/feed/",                                                                      "tier": 2},
    # Tier 3 — High-volume news sites (poll every 2 hr, keyword-filtered)
    {"name": "VentureBeat AI","url": "https://venturebeat.com/category/ai/feed/",                                                          "tier": 3},
    {"name": "The Verge AI",  "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",                                  "tier": 3},
    {"name": "Wired AI",      "url": "https://www.wired.com/feed/tag/ai/latest/rss",                                                       "tier": 3},
    {"name": "Towards Data Science","url": "https://towardsdatascience.com/feed/",                                                         "tier": 3},
    # ArXiv — keyword-filtered, separate handling
    {"name": "arXiv cs.AI",   "url": "http://arxiv.org/rss/cs.AI",  "tier": 2, "is_arxiv": True},
    {"name": "arXiv cs.LG",   "url": "http://arxiv.org/rss/cs.LG",  "tier": 2, "is_arxiv": True},
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
