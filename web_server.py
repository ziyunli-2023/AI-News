"""FastAPI web server — real-time AI news dashboard with WebSocket push."""

import json
import logging
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

import storage
import config

logger = logging.getLogger(__name__)

app = FastAPI(title="AI News Monitor")

# ── WebSocket connection manager ───────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self._connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.add(ws)
        logger.debug("WS client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket):
        self._connections.discard(ws)

    async def broadcast(self, data: dict):
        dead = set()
        for ws in self._connections:
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                dead.add(ws)
        self._connections -= dead

manager = ConnectionManager()


async def push_new_item(item: dict, item_type: str):
    """Called by monitors when a new item arrives — pushes to all WS clients."""
    await manager.broadcast({"type": item_type, "data": item})


# ── REST API ───────────────────────────────────────────────────────────────

@app.get("/api/news")
def get_news(limit: int = 30, source: str = None):
    tweets = storage.get_latest_tweets(limit=limit)
    posts  = storage.get_latest_posts(limit=limit, source=source)
    items  = []
    for t in tweets:
        items.append({"type": "tweet", "date": t["created_at"], "data": t})
    for p in posts:
        items.append({"type": "post", "date": p.get("published", ""), "data": p})
    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:limit]


@app.get("/api/search")
def search(q: str, limit: int = 20):
    return storage.search_news(query=q, limit=limit)


@app.get("/api/stats")
def stats():
    return storage.get_stats()


@app.get("/api/health")
def health():
    return {"status": "ok", "feeds": len(config.RSS_FEEDS)}


@app.get("/api/digest-summary")
def digest_summary():
    """Generate an on-demand AI digest summary of the latest news."""
    import ai_processor
    posts  = storage.get_latest_posts(limit=20)
    tweets = storage.get_latest_tweets(limit=10)
    items  = [{"type": "post",  "data": p} for p in posts]
    items += [{"type": "tweet", "data": t} for t in tweets]
    summary = ai_processor.generate_digest_summary(items)
    return {"summary": summary}


@app.get("/api/briefing")
def daily_briefing():
    """Generate structured daily briefing with sections: AI, Web3, 创投, 美股, 港股."""
    import ai_processor
    posts_by_cat = storage.get_recent_posts_by_category(hours=24, limit_per_category=10)
    return ai_processor.generate_daily_briefing(posts_by_cat)


# ── WebSocket ──────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep connection alive
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ── Dashboard HTML ─────────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh" data-theme="auto">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>News Monitor</title>
<style>
  /* ── Tokens ── */
  :root {
    --bg: #f5f6f8; --surface: #ffffff; --surface2: #f0f1f4;
    --border: #e2e4e9; --border2: #ced0d6;
    --text: #111318; --text2: #4a4f5c; --muted: #8a8fa0;
    --accent: #2563eb; --accent-bg: #eff4ff;
    --green: #16a34a; --green-bg: #f0fdf4;
    --red: #dc2626; --tweet: #1d9bf0; --tweet-bg: #eff8ff;
    --shadow: 0 1px 3px rgba(0,0,0,.08);
  }
  [data-theme="dark"] {
    --bg: #0f1117; --surface: #181c25; --surface2: #1e2330;
    --border: #2a2f3d; --border2: #363c4e;
    --text: #e8eaf0; --text2: #9ba3b8; --muted: #5c6378;
    --accent: #4f8ef7; --accent-bg: #1a2540;
    --green: #34d399; --green-bg: #0d2418;
    --red: #f87171; --tweet: #38bdf8; --tweet-bg: #0c1f2e;
    --shadow: 0 1px 4px rgba(0,0,0,.3);
  }
  @media (prefers-color-scheme: dark) {
    [data-theme="auto"] {
      --bg: #0f1117; --surface: #181c25; --surface2: #1e2330;
      --border: #2a2f3d; --border2: #363c4e;
      --text: #e8eaf0; --text2: #9ba3b8; --muted: #5c6378;
      --accent: #4f8ef7; --accent-bg: #1a2540;
      --green: #34d399; --green-bg: #0d2418;
      --red: #f87171; --tweet: #38bdf8; --tweet-bg: #0c1f2e;
      --shadow: 0 1px 4px rgba(0,0,0,.3);
    }
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif; font-size: 14px; line-height: 1.5; }

  /* ── Layout ── */
  .layout { display: flex; height: 100vh; overflow: hidden; }
  .sidebar { width: 220px; background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; overflow-y: auto; }
  .main { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; }

  /* ── Sidebar ── */
  .sidebar-logo { padding: 18px 16px 14px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
  .sidebar-logo h1 { font-size: 14px; font-weight: 700; color: var(--text); letter-spacing: -.01em; }
  .status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--green); display: inline-block; margin-right: 7px; animation: pulse 2.5s infinite; flex-shrink: 0; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
  .theme-btn { background: none; border: 1px solid var(--border); border-radius: 6px; color: var(--muted); font-size: 14px; width: 28px; height: 28px; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
  .theme-btn:hover { border-color: var(--accent); color: var(--accent); }

  .nav-section { padding: 14px 12px 4px; font-size: 10px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .1em; }
  .nav-btn { display: flex; align-items: center; gap: 8px; width: 100%; padding: 7px 12px; background: none; border: none; color: var(--text2); font-size: 13px; cursor: pointer; text-align: left; border-radius: 6px; margin: 1px 4px; width: calc(100% - 8px); transition: background .12s, color .12s; }
  .nav-btn:hover { background: var(--surface2); color: var(--text); }
  .nav-btn.active { background: var(--accent-bg); color: var(--accent); font-weight: 600; }
  .nav-btn .cnt { margin-left: auto; font-size: 11px; color: var(--muted); background: var(--surface2); padding: 1px 6px; border-radius: 8px; }
  .nav-btn.active .cnt { background: var(--accent-bg); color: var(--accent); }

  .stats-box { margin: auto 12px 16px; background: var(--surface2); border-radius: 8px; padding: 12px; }
  .stat-row { display: flex; justify-content: space-between; font-size: 12px; padding: 3px 0; }
  .stat-label { color: var(--muted); }
  .stat-val { color: var(--text); font-weight: 500; font-variant-numeric: tabular-nums; }
  .status-text { font-size: 11px; color: var(--muted); margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); }

  /* ── Topbar ── */
  .topbar { padding: 12px 20px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 10px; background: var(--surface); flex-shrink: 0; }
  .search-wrap { flex: 1; position: relative; }
  .search-wrap input { width: 100%; background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 7px 12px 7px 34px; color: var(--text); font-size: 13px; outline: none; transition: border-color .15s; }
  .search-wrap input::placeholder { color: var(--muted); }
  .search-wrap input:focus { border-color: var(--accent); background: var(--surface); }
  .search-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--muted); font-size: 14px; pointer-events: none; }
  .new-pill { background: var(--red); color: #fff; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 20px; display: none; cursor: pointer; white-space: nowrap; }
  .new-pill.show { display: block; }

  /* ── Feed ── */
  .feed { flex: 1; overflow-y: auto; padding: 16px 20px; }
  .feed::-webkit-scrollbar { width: 5px; }
  .feed::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 3px; }

  /* ── Briefing ── */
  .briefing-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; margin-bottom: 14px; box-shadow: var(--shadow); }
  .panel-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
  .panel-title { font-size: 13px; font-weight: 700; color: var(--text); display: flex; align-items: center; gap: 6px; }
  .panel-actions { display: flex; align-items: center; gap: 8px; }
  .panel-meta { font-size: 11px; color: var(--muted); }
  .refresh-btn { background: none; border: 1px solid var(--border); border-radius: 5px; color: var(--muted); font-size: 12px; padding: 3px 9px; cursor: pointer; transition: border-color .12s, color .12s; }
  .refresh-btn:hover { border-color: var(--accent); color: var(--accent); }

  .briefing-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
  @media (max-width: 1100px) { .briefing-grid { grid-template-columns: repeat(3, 1fr); } }
  @media (max-width: 720px)  { .briefing-grid { grid-template-columns: 1fr 1fr; } }

  .b-section { background: var(--surface2); border-radius: 8px; padding: 12px 13px; border: 1px solid var(--border); }
  .b-title { font-size: 12px; font-weight: 700; color: var(--text); margin-bottom: 9px; }
  .b-list { list-style: none; }
  .b-list li { font-size: 12px; color: var(--text2); line-height: 1.5; padding: 4px 0 4px 14px; position: relative; border-bottom: 1px solid var(--border); }
  .b-list li:last-child { border-bottom: none; padding-bottom: 0; }
  .b-list li::before { content: "·"; position: absolute; left: 3px; color: var(--accent); font-weight: 900; font-size: 14px; line-height: 1.4; }
  .panel-loading { font-size: 12px; color: var(--muted); padding: 4px 0; }

  /* ── Digest ── */
  .digest-panel { background: var(--accent-bg); border: 1px solid var(--border); border-radius: 12px; padding: 14px 18px; margin-bottom: 14px; }
  .digest-text { font-size: 13px; color: var(--text2); line-height: 1.75; }

  /* ── Cards ── */
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; box-shadow: var(--shadow); transition: border-color .15s, box-shadow .15s; }
  .card:hover { border-color: var(--border2); box-shadow: 0 2px 8px rgba(0,0,0,.1); }
  .card.new-item { animation: slideIn .25s ease; border-color: var(--accent); }
  @keyframes slideIn { from { opacity:0; transform:translateY(-6px); } to { opacity:1; transform:translateY(0); } }

  .card-meta { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; }
  .tag { font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; white-space: nowrap; }
  .tag-post  { background: var(--accent-bg); color: var(--accent); }
  .tag-tweet { background: var(--tweet-bg); color: var(--tweet); }
  .tag-t1    { background: var(--green-bg); color: var(--green); }
  .tag-cat   { background: var(--surface2); color: var(--muted); }
  .card-date { font-size: 11px; color: var(--muted); margin-left: auto; }

  .card-title { font-size: 15px; font-weight: 600; line-height: 1.4; color: var(--text); margin-bottom: 4px; }
  .card-title a { color: inherit; text-decoration: none; }
  .card-title a:hover { color: var(--accent); }
  .card-title-zh { font-size: 13px; color: var(--text2); margin-bottom: 8px; font-weight: 400; }

  .card-summary-zh { font-size: 13px; color: var(--text2); line-height: 1.6; margin-bottom: 4px; }
  .card-summary-en { font-size: 12px; color: var(--muted); line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; margin-bottom: 10px; }

  .card-footer { display: flex; align-items: center; gap: 10px; margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border); }
  .card-link { font-size: 12px; color: var(--accent); text-decoration: none; font-weight: 500; }
  .card-link:hover { text-decoration: underline; }
  .card-eng { font-size: 12px; color: var(--muted); margin-left: auto; }

  .tweet-text { font-size: 14px; color: var(--text); line-height: 1.6; margin-bottom: 2px; }

  .empty { text-align: center; padding: 50px 20px; color: var(--muted); }
  .empty-icon { font-size: 36px; margin-bottom: 10px; }
  .loading-text { text-align: center; padding: 20px; color: var(--muted); font-size: 13px; }
</style>
</head>
<body>
<div class="layout">

  <!-- Sidebar -->
  <aside class="sidebar">
    <div class="sidebar-logo">
      <h1><span class="status-dot" id="statusDot"></span>News Monitor</h1>
      <button class="theme-btn" id="themeBtn" title="切换主题" onclick="toggleTheme()">☀</button>
    </div>

    <div class="nav-section">筛选</div>
    <button class="nav-btn active" onclick="setFilter('all',this)">🌐 全部 <span class="cnt" id="cnt-all">0</span></button>
    <button class="nav-btn" onclick="setFilter('posts',this)">📰 博客文章 <span class="cnt" id="cnt-posts">0</span></button>
    <button class="nav-btn" onclick="setFilter('tweets',this)">𝕏 推文 <span class="cnt" id="cnt-tweets">0</span></button>

    <div class="nav-section" style="margin-top:6px;">来源</div>
    <div id="sourceList"></div>

    <div class="stats-box">
      <div class="stat-row"><span class="stat-label">文章</span><span class="stat-val" id="statPosts">—</span></div>
      <div class="stat-row"><span class="stat-label">推文</span><span class="stat-val" id="statTweets">—</span></div>
      <div class="stat-row"><span class="stat-label">最新</span><span class="stat-val" id="statLast">—</span></div>
      <div class="status-text" id="statusText">连接中…</div>
    </div>
  </aside>

  <!-- Main -->
  <div class="main">
    <div class="topbar">
      <div class="search-wrap">
        <span class="search-icon">🔍</span>
        <input type="text" id="searchInput" placeholder="搜索新闻…" oninput="onSearch(this.value)">
      </div>
      <div class="new-pill" id="newBadge" onclick="scrollToTop()">↑ 有新内容</div>
    </div>

    <div class="feed" id="feed">
      <!-- 速报 -->
      <div class="briefing-panel">
        <div class="panel-header">
          <div class="panel-title">⚡ 每日要闻速报</div>
          <div class="panel-actions">
            <span class="panel-meta" id="briefingMeta"></span>
            <button class="refresh-btn" onclick="loadBriefing()">↻ 刷新</button>
          </div>
        </div>
        <div id="briefingBody"><span class="panel-loading">正在生成速报…</span></div>
      </div>

      <!-- AI 摘要 -->
      <div class="digest-panel">
        <div class="panel-header">
          <div class="panel-title">📋 AI 资讯摘要</div>
          <div class="panel-actions">
            <button class="refresh-btn" onclick="loadDigest()">↻ 刷新</button>
          </div>
        </div>
        <div class="digest-text" id="digestText"><span class="panel-loading">正在生成摘要…</span></div>
      </div>

      <div id="cardFeed"><div class="loading-text">加载中…</div></div>
    </div>
  </div>
</div>

<script>
let allItems = [], currentFilter = 'all', ws;

// ── Theme ──────────────────────────────────────────────────────────────────
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  document.getElementById('themeBtn').textContent = t === 'dark' ? '☀' : '🌙';
  localStorage.setItem('theme', t);
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme');
  const isDark = cur === 'dark' || (cur === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  applyTheme(isDark ? 'light' : 'dark');
}
(function initTheme() {
  const saved = localStorage.getItem('theme');
  if (saved) applyTheme(saved);
  else applyTheme('auto');
})();

// ── WebSocket ──────────────────────────────────────────────────────────────
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    document.getElementById('statusDot').style.background = 'var(--green)';
    document.getElementById('statusText').textContent = '实时连接';
  };
  ws.onclose = () => {
    document.getElementById('statusDot').style.background = 'var(--red)';
    document.getElementById('statusText').textContent = '重连中…';
    setTimeout(connectWS, 3000);
  };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    const item = { type: msg.type, date: msg.data.created_at || msg.data.published || '', data: msg.data };
    allItems.unshift(item);
    updateCounts();
    if (currentFilter === 'all' || currentFilter === msg.type + 's') { prependCard(item, true); showNewBadge(); }
    updateStats();
  };
}

// ── Data ──────────────────────────────────────────────────────────────────
async function loadNews() {
  const res = await fetch('/api/news?limit=50');
  allItems = await res.json();
  renderFeed(); updateCounts(); updateStats();
}
async function updateStats() {
  const s = await fetch('/api/stats').then(r => r.json());
  document.getElementById('statPosts').textContent = s.post_count.toLocaleString();
  document.getElementById('statTweets').textContent = s.tweet_count.toLocaleString();
  const last = s.latest_post_at || s.latest_tweet_at;
  document.getElementById('statLast').textContent = last ? last.slice(0,16).replace('T',' ') : '—';
}

// ── Render ────────────────────────────────────────────────────────────────
function renderFeed() {
  const feed = document.getElementById('cardFeed');
  const filtered = filterItems(allItems);
  if (!filtered.length) {
    feed.textContent = '';
    const empty = document.createElement('div');
    empty.className = 'empty';
    const icon = document.createElement('div');
    icon.className = 'empty-icon';
    icon.textContent = '📭';
    const msg = document.createElement('div');
    msg.textContent = '暂无内容，监控器正在抓取…';
    empty.appendChild(icon); empty.appendChild(msg);
    feed.appendChild(empty);
    return;
  }
  feed.textContent = '';
  filtered.forEach(item => feed.appendChild(makeCard(item, false)));
  buildSourceList();
}

function prependCard(item, isNew) {
  const feed = document.getElementById('cardFeed');
  const emptyEl = feed.querySelector('.empty, .loading-text');
  if (emptyEl) emptyEl.remove();
  feed.insertBefore(makeCard(item, isNew), feed.firstChild);
}

function makeCard(item, isNew) {
  const d = item.data, isPost = item.type === 'post';
  const date = (d.created_at || d.published || '').slice(0,16).replace('T',' ');
  const div = document.createElement('div');
  div.className = 'card' + (isNew ? ' new-item' : '');

  // Meta row
  const meta = document.createElement('div');
  meta.className = 'card-meta';

  const srcTag = document.createElement('span');
  if (isPost) {
    srcTag.className = 'tag tag-post';
    srcTag.textContent = '📰 ' + d.source;
  } else {
    srcTag.className = 'tag tag-tweet';
    srcTag.textContent = '𝕏 @' + d.username;
  }
  meta.appendChild(srcTag);

  if (isPost && d.feed_priority === 1) {
    const t1 = document.createElement('span');
    t1.className = 'tag tag-t1'; t1.textContent = '精选';
    meta.appendChild(t1);
  }
  if (!isPost && d.category) {
    const cat = document.createElement('span');
    cat.className = 'tag tag-cat'; cat.textContent = d.category;
    meta.appendChild(cat);
  }

  const dateEl = document.createElement('span');
  dateEl.className = 'card-date'; dateEl.textContent = date;
  meta.appendChild(dateEl);
  div.appendChild(meta);

  if (isPost) {
    const titleEl = document.createElement('div');
    titleEl.className = 'card-title';
    const a = document.createElement('a');
    a.href = d.url; a.target = '_blank'; a.textContent = d.title;
    titleEl.appendChild(a);
    div.appendChild(titleEl);

    if (d.title_zh) {
      const zh = document.createElement('div');
      zh.className = 'card-title-zh'; zh.textContent = d.title_zh;
      div.appendChild(zh);
    }
    if (d.summary_zh) {
      const sz = document.createElement('div');
      sz.className = 'card-summary-zh'; sz.textContent = d.summary_zh;
      div.appendChild(sz);
    }
    if (d.summary) {
      const se = document.createElement('div');
      se.className = 'card-summary-en'; se.textContent = d.summary;
      div.appendChild(se);
    }
    const footer = document.createElement('div');
    footer.className = 'card-footer';
    const link = document.createElement('a');
    link.className = 'card-link'; link.href = d.url; link.target = '_blank'; link.textContent = '阅读原文 →';
    footer.appendChild(link);
    div.appendChild(footer);
  } else {
    const txt = document.createElement('div');
    txt.className = 'tweet-text'; txt.textContent = d.text;
    div.appendChild(txt);
    const footer = document.createElement('div');
    footer.className = 'card-footer';
    const link = document.createElement('a');
    link.className = 'card-link'; link.href = d.url || '#'; link.target = '_blank'; link.textContent = '查看推文 →';
    footer.appendChild(link);
    const eng = document.createElement('span');
    eng.className = 'card-eng';
    eng.textContent = '❤ ' + (d.likes||0) + '  🔁 ' + (d.retweets||0);
    footer.appendChild(eng);
    div.appendChild(footer);
  }
  return div;
}

// ── Filters ───────────────────────────────────────────────────────────────
function filterItems(items) {
  if (currentFilter === 'posts')  return items.filter(i => i.type === 'post');
  if (currentFilter === 'tweets') return items.filter(i => i.type === 'tweet');
  return items;
}
function setFilter(f, btn) {
  currentFilter = f;
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderFeed();
}
function updateCounts() {
  document.getElementById('cnt-all').textContent    = allItems.length;
  document.getElementById('cnt-posts').textContent  = allItems.filter(i=>i.type==='post').length;
  document.getElementById('cnt-tweets').textContent = allItems.filter(i=>i.type==='tweet').length;
}
function buildSourceList() {
  const counts = {};
  allItems.filter(i=>i.type==='post').forEach(i => { counts[i.data.source] = (counts[i.data.source]||0)+1; });
  const top = Object.entries(counts).sort((a,b)=>b[1]-a[1]).slice(0,6);
  const el = document.getElementById('sourceList');
  el.textContent = '';
  top.forEach(([src, cnt]) => {
    const btn = document.createElement('button');
    btn.className = 'nav-btn';
    btn.style.fontSize = '12px';
    btn.onclick = () => filterSource(src, btn);
    btn.textContent = src;
    const badge = document.createElement('span');
    badge.className = 'cnt'; badge.textContent = cnt;
    btn.appendChild(badge);
    el.appendChild(btn);
  });
}
function filterSource(src, btn) {
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  const feed = document.getElementById('cardFeed');
  feed.textContent = '';
  allItems.filter(i => i.data.source === src).forEach(item => feed.appendChild(makeCard(item, false)));
}

// ── Briefing ──────────────────────────────────────────────────────────────
async function loadBriefing() {
  const body = document.getElementById('briefingBody');
  const meta = document.getElementById('briefingMeta');
  body.textContent = '正在生成速报…';
  try {
    const data = await fetch('/api/briefing').then(r => r.json());
    const sections = data.sections || [];
    if (!sections.length) { body.textContent = '暂无数据'; return; }

    const grid = document.createElement('div');
    grid.className = 'briefing-grid';
    sections.forEach(s => {
      const sec = document.createElement('div'); sec.className = 'b-section';
      const title = document.createElement('div'); title.className = 'b-title';
      title.textContent = (s.icon||'') + ' ' + (s.label||s.category);
      sec.appendChild(title);
      const ul = document.createElement('ul'); ul.className = 'b-list';
      (s.points||[]).forEach(p => { const li = document.createElement('li'); li.textContent = p; ul.appendChild(li); });
      sec.appendChild(ul); grid.appendChild(sec);
    });
    body.textContent = '';
    body.appendChild(grid);
    meta.textContent = new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}) + ' 更新';
  } catch(e) { body.textContent = '速报生成失败'; }
}

// ── Digest ────────────────────────────────────────────────────────────────
async function loadDigest() {
  const el = document.getElementById('digestText');
  el.textContent = '正在生成摘要…';
  try {
    const data = await fetch('/api/digest-summary').then(r => r.json());
    el.textContent = data.summary || '暂无摘要';
  } catch(e) { el.textContent = '摘要生成失败'; }
}

// ── Search ────────────────────────────────────────────────────────────────
let searchTimer;
async function onSearch(q) {
  clearTimeout(searchTimer);
  if (!q.trim()) { renderFeed(); return; }
  searchTimer = setTimeout(async () => {
    const results = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=30`).then(r=>r.json());
    const feed = document.getElementById('cardFeed');
    feed.textContent = '';
    if (!results.length) {
      const empty = document.createElement('div'); empty.className = 'empty';
      const icon = document.createElement('div'); icon.className = 'empty-icon'; icon.textContent = '🔍';
      const msg = document.createElement('div'); msg.textContent = '未找到 "' + q + '"';
      empty.appendChild(icon); empty.appendChild(msg); feed.appendChild(empty);
      return;
    }
    results.forEach(r => {
      const isPost = !r.text;
      feed.appendChild(makeCard({ type: isPost?'post':'tweet', date: r.created_at||r.published||'', data: r }, false));
    });
  }, 300);
}

// ── Helpers ───────────────────────────────────────────────────────────────
function showNewBadge() {
  const b = document.getElementById('newBadge'); b.classList.add('show');
  setTimeout(() => b.classList.remove('show'), 5000);
}
function scrollToTop() {
  document.getElementById('feed').scrollTo({top:0,behavior:'smooth'});
  document.getElementById('newBadge').classList.remove('show');
}

// ── Init ──────────────────────────────────────────────────────────────────
loadNews(); connectWS(); loadBriefing(); loadDigest();
setInterval(updateStats, 60000);
setInterval(loadBriefing, 30 * 60 * 1000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)
