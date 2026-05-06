# AI News Monitor

> Track AI news from X and RSS in one lightweight, self-hosted monitor.

AI News Monitor collects updates from leading AI researchers, labs, founders, and technical blogs across X (Twitter) and RSS feeds, stores everything in SQLite, and serves the results through a local web dashboard. It can also send email digests, translate content into Chinese with DeepSeek, and expose the dataset through an MCP server for coding agents and local tooling.

**Features:**
- **X Monitor** — Track 8 key AI figures (Karpathy, Sam Altman, etc.) · Free tier
- **RSS Monitor** — OpenAI, Anthropic, DeepMind, arXiv and 22 more, tiered polling
- **AI Translation** — DeepSeek API auto-translates English titles/summaries to Chinese *(optional)*
- **Email Digest** — Gmail notifications when new content arrives *(optional)*
- **Web Dashboard** — Browse all news at `http://localhost:8000`
- **MCP Server** — Claude Code can query the database directly via MCP tools

---

## Quick Start

### Choose Your Deployment Method

**🐳 Docker (Recommended for Production)**
- Production-ready with HTTPS/SSL
- Nginx reverse proxy
- Automated backups
- One-command deployment

👉 **[Docker Deployment Guide →](README-DOCKER.md)** | **[Quick Reference](DOCKER-QUICKREF.md)**

```bash
# Local development
./scripts/setup.sh

# Production with SSL
USE_LETSENCRYPT=true DOMAIN=your-domain.com SSL_EMAIL=you@email.com ./scripts/setup.sh
```

**🐍 Python (Simple Setup)**
- Direct Python execution
- Good for development/testing
- No containerization needed

### Python Installation

**1. Clone & install dependencies**

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

## Running the Service

### Manual start

```bash
# Foreground (useful for debugging)
python main.py

# Background, logging to main.log
python main.py >> logs/main.log 2>&1 &
```

### Check if the service is running

```bash
ps aux | grep main.py | grep -v grep
```

If the output is empty, the process is not running. Restart it manually or via launchd (see below).

---

## 7x24 Running and Auto-Start

For long-running deployment, use the Docker stack. `docker-compose.yml` already sets `restart: unless-stopped`, and you can add a `systemd` unit so the stack starts automatically after boot.

### Linux / WSL recommended setup

```bash
# 1. Prepare config
cp .env.example .env

# 2. Initial setup and first start
./scripts/setup.sh

# 3. Install systemd auto-start service
./scripts/install-systemd-service.sh
```

Useful commands:

```bash
sudo systemctl status ai-news-docker
sudo systemctl restart ai-news-docker
sudo journalctl -u ai-news-docker -f
docker compose ps
docker compose logs -f
```

### WSL extra step

If `systemctl` is unavailable in WSL, enable systemd first:

```bash
./scripts/enable-wsl-systemd.sh
```

Then run `wsl.exe --shutdown` in Windows PowerShell, reopen WSL, and rerun `./scripts/install-systemd-service.sh`.

### Windows boot auto-start for WSL

`systemd` only helps after the WSL distro has started. If you want the service to start automatically when Windows boots, add a Windows Scheduled Task that launches WSL and starts `ai-news-docker.service`.

Current detected distro example:

```powershell
Ubuntu-22.04
```

Run this in **Windows PowerShell as Administrator**:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\liziy\Code\AI-News\scripts\windows\register-ai-news-startup-task.ps1 -DistroName "Ubuntu-22.04" -ProjectDir "C:\Users\liziy\Code\AI-News"
```

This creates a startup task named `AI-News-WSL-Autostart`. It runs:

```powershell
C:\Users\liziy\Code\AI-News\scripts\windows\start-ai-news-wsl.ps1
```

That script launches WSL as `root` and executes:

```bash
systemctl start ai-news-docker.service
```

Useful Windows-side commands:

```powershell
Start-ScheduledTask -TaskName "AI-News-WSL-Autostart"
Get-ScheduledTask -TaskName "AI-News-WSL-Autostart"
schtasks /Query /TN "AI-News-WSL-Autostart"
```

Useful WSL-side checks:

```bash
systemctl status ai-news-docker.service --no-pager
docker compose ps
```

---

## Auto-start on macOS (launchd)

The service is managed by macOS `launchd` and is configured to **start at login** and **restart automatically on crash**.

### Plist location

```
~/Library/LaunchAgents/com.ziyun.news-monitor.plist
```

### Plist contents

Adjust the Python path to match your environment (use `which python3` to find it). If using a Conda environment, point to the env's interpreter directly:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ziyun.news-monitor</string>

    <key>ProgramArguments</key>
    <array>
        <!-- Use your Conda env's python, or /usr/bin/python3 -->
        <string>/Users/ziyun/opt/anaconda3/envs/cli-env/bin/python3</string>
        <string>/Users/ziyun/Documents/Code/News/main.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/ziyun/Documents/Code/News</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/Users/ziyun/opt/anaconda3/envs/cli-env/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>

    <!-- Start at login -->
    <key>RunAtLoad</key>
    <true/>

    <!-- Restart automatically if it crashes -->
    <key>KeepAlive</key>
    <true/>

    <!-- Log output (launchd-managed runs) -->
    <key>StandardOutPath</key>
    <string>/Users/ziyun/Documents/Code/News/logs/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/ziyun/Documents/Code/News/logs/stderr.log</string>
</dict>
</plist>
```

> **Note:** `WorkingDirectory` must be set correctly — the service reads `.env` and `news.db` relative to this path.

### Managing the service

```bash
# Install / reload after editing the plist
launchctl load ~/Library/LaunchAgents/com.ziyun.news-monitor.plist

# Check status
# Output format: <PID>  <exit-code>  <label>
# "-" in PID column = not running; exit code -9 = killed by OS
launchctl list | grep news-monitor

# Stop the service
launchctl unload ~/Library/LaunchAgents/com.ziyun.news-monitor.plist

# Restart
launchctl unload ~/Library/LaunchAgents/com.ziyun.news-monitor.plist
launchctl load ~/Library/LaunchAgents/com.ziyun.news-monitor.plist
```

### Viewing logs

| Log file | Written by |
|---|---|
| `logs/main.log` | Manual runs (`python main.py >> logs/main.log 2>&1 &`) |
| `logs/stdout.log` | launchd-managed runs (stdout) |
| `logs/stderr.log` | launchd-managed runs (stderr) |

```bash
# Follow logs in real time
tail -f logs/main.log
tail -f logs/stderr.log
```

### Troubleshooting: service exits silently after launchd start

If `launchctl list | grep news-monitor` shows `- 0` (PID is `-`, exit code is `0`) right after loading, the process started and exited cleanly with no error. Common causes:

- **Wrong Python path** — verify with `/path/to/python3 --version`
- **Missing `.env`** — the service reads credentials from `.env` in the working directory; make sure it exists
- **WorkingDirectory not set** — without it, relative paths like `news.db` and `.env` won't resolve

As a fallback, start the service manually:

```bash
python main.py >> logs/main.log 2>&1 &
```

### Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.ziyun.news-monitor.plist
rm ~/Library/LaunchAgents/com.ziyun.news-monitor.plist
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
