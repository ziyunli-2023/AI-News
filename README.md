# AI News Monitor

> 自动追踪 AI 圈动态 | Auto-track AI industry news

Monitor AI researchers on X (Twitter) + 22 RSS sources, store in SQLite, browse via a web dashboard, and expose data to Claude Code via MCP server.

**Features:**
- **X Monitor** — Track 8 key AI figures (Karpathy, Sam Altman, etc.) · Free tier
- **RSS Monitor** — OpenAI, Anthropic, DeepMind, arXiv and 22 more, tiered polling
- **AI Translation** — DeepSeek API auto-translates English titles/summaries to Chinese *(optional)*
- **Email Digest** — Gmail notifications when new content arrives *(optional)*
- **Web Dashboard** — Browse all news at `http://localhost:8000`
- **MCP Server** — Claude Code can query the database directly via MCP tools

---

## Quick Start

### 1. Clone & install dependencies

```bash
git clone https://github.com/ziyunli-2023/AI-News.git
cd AI-News
pip install -r requirements.txt uvicorn
```

### 2. Configure environment variables

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Required for tweet monitoring (leave empty to skip)
X_BEARER_TOKEN=your_bearer_token_here

# Required for email notifications (leave empty to disable)
EMAIL_SENDER=your_gmail@gmail.com
EMAIL_APP_PASSWORD=xxxx_xxxx_xxxx_xxxx
EMAIL_RECIPIENT=where_to_receive@example.com

# Required for Chinese translation (leave empty to disable)
DEEPSEEK_API_KEY=sk-your_deepseek_key_here

# Web dashboard port
WEB_PORT=8000
```

**All fields are optional** — the monitor runs fine with all fields empty (no tweets, no email, no translation).

#### Getting API keys

| Service | How to get |
|---|---|
| X Bearer Token | [developer.twitter.com](https://developer.twitter.com/en/portal/dashboard) → Create app → Bearer Token |
| Gmail App Password | Google Account → Security → 2-Step Verification → App Passwords |
| DeepSeek API Key | [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) |

### 3. Run

```bash
python main.py
```

Open web dashboard: `http://localhost:8000`

---

## MCP Server (for Claude Code)

Run as an MCP server so Claude Code can query your news database directly:

```bash
python mcp_server.py
```

Add to your Claude Code MCP config (`~/.claude/settings.json` or `.mcp.json`):

```json
{
  "mcpServers": {
    "ai-news-monitor": {
      "command": "python",
      "args": ["/path/to/AI-News/mcp_server.py"]
    }
  }
}
```

### Available MCP Tools

| Tool | Description |
|---|---|
| `get_latest_tweets` | Latest tweets, filterable by user |
| `get_latest_blog_posts` | Latest blog posts, filterable by source |
| `get_all_news` | Mixed feed of tweets + posts |
| `get_new_since_last_check` | New content since last query |
| `get_stats` | Database statistics |
| `list_tracked_sources` | All tracked sources |
| `search_news` | Full-text search |
| `get_top_posts` | Top content by engagement |
| `get_health` | Monitor health status |
| `get_by_category` | Filter by category (researcher/founder/safety/etc.) |

---

## Auto-start on macOS (launchd)

To run the monitor automatically at login:

### 1. Create the plist file

Create `~/Library/LaunchAgents/com.yourname.news-monitor.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.yourname.news-monitor</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/path/to/AI-News/main.py</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/path/to/AI-News/logs/stdout.log</string>
  <key>StandardErrorPath</key>
  <string>/path/to/AI-News/logs/stderr.log</string>
</dict>
</plist>
```

### 2. Install & manage the service

```bash
# Load (install / reload after editing plist)
launchctl load ~/Library/LaunchAgents/com.yourname.news-monitor.plist

# Check status (first col = PID, "-" means not running; second col = exit code)
launchctl list | grep news-monitor

# Stop
launchctl unload ~/Library/LaunchAgents/com.yourname.news-monitor.plist

# Start
launchctl load ~/Library/LaunchAgents/com.yourname.news-monitor.plist

# View logs
tail -f /path/to/AI-News/logs/stdout.log
tail -f /path/to/AI-News/logs/stderr.log
```

### 3. Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.yourname.news-monitor.plist
rm ~/Library/LaunchAgents/com.yourname.news-monitor.plist
```

---

## Project Structure

```
AI-News/
├── main.py           # Entry point: Web dashboard + monitors + email
├── mcp_server.py     # MCP server entry (for Claude Code)
├── config.py         # Tracked accounts, RSS sources, polling intervals
├── storage.py        # SQLite database operations
├── rss_monitor.py    # RSS polling monitor
├── nitter_monitor.py # X (Twitter) monitor
├── x_monitor.py      # X API wrapper
├── ai_processor.py   # DeepSeek translation
├── notifier.py       # Email notifications
├── web_server.py     # FastAPI web dashboard
├── .env.example      # Environment variable template
├── requirements.txt  # Python dependencies
└── logs/             # Runtime logs (auto-created, not tracked in git)
```

## Customizing Tracked Sources

Edit `config.py` to add/remove:
- X accounts to follow
- RSS feeds to monitor
- Polling intervals per source tier

---

## License

MIT
