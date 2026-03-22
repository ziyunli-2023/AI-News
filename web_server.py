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
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI News Monitor</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --orange: #d29922; --red: #f85149;
    --tier1: #58a6ff; --tweet: #1d9bf0;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }

  /* Layout */
  .layout { display: flex; height: 100vh; overflow: hidden; }
  .sidebar { width: 240px; background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; }
  .main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

  /* Sidebar */
  .sidebar-header { padding: 20px 16px 12px; border-bottom: 1px solid var(--border); }
  .sidebar-header h1 { font-size: 15px; font-weight: 600; color: var(--accent); }
  .sidebar-header .sub { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--green); margin-right: 6px; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
  .sidebar-section { padding: 12px 16px 4px; font-size: 11px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
  .filter-btn { display: flex; align-items: center; gap: 8px; width: 100%; padding: 7px 16px; background: none; border: none; color: var(--text); font-size: 13px; cursor: pointer; text-align: left; border-radius: 0; }
  .filter-btn:hover { background: rgba(255,255,255,.05); }
  .filter-btn.active { background: rgba(88,166,255,.1); color: var(--accent); }
  .filter-btn .count { margin-left: auto; font-size: 11px; color: var(--muted); background: var(--border); padding: 1px 6px; border-radius: 10px; }
  .stats-box { margin: auto 16px 16px; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
  .stat-row { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 6px; }
  .stat-row:last-child { margin-bottom: 0; }
  .stat-label { color: var(--muted); }
  .stat-val { color: var(--text); font-weight: 500; }

  /* Top bar */
  .topbar { padding: 14px 20px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 12px; background: var(--surface); }
  .search-wrap { flex: 1; position: relative; }
  .search-wrap input { width: 100%; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px 8px 36px; color: var(--text); font-size: 14px; outline: none; }
  .search-wrap input:focus { border-color: var(--accent); }
  .search-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--muted); font-size: 15px; }
  .new-badge { background: var(--red); color: #fff; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 12px; display: none; cursor: pointer; }
  .new-badge.show { display: inline-block; }

  /* Feed */
  .feed { flex: 1; overflow-y: auto; padding: 16px 20px; }
  .feed::-webkit-scrollbar { width: 6px; }
  .feed::-webkit-scrollbar-track { background: transparent; }
  .feed::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

  /* Card */
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; margin-bottom: 12px; transition: border-color .15s; }
  .card:hover { border-color: #484f58; }
  .card.new-item { animation: slideIn .3s ease; border-color: var(--accent); }
  @keyframes slideIn { from { opacity:0; transform:translateY(-8px); } to { opacity:1; transform:translateY(0); } }
  .card-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .source-tag { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px; }
  .tag-post { background: rgba(88,166,255,.15); color: var(--tier1); }
  .tag-tweet { background: rgba(29,155,240,.15); color: var(--tweet); }
  .tag-tier1 { background: rgba(63,185,80,.15); color: var(--green); }
  .card-date { font-size: 11px; color: var(--muted); margin-left: auto; }
  .card-title { font-size: 15px; font-weight: 600; line-height: 1.4; margin-bottom: 6px; }
  .card-title a { color: var(--text); text-decoration: none; }
  .card-title a:hover { color: var(--accent); }
  .card-summary { font-size: 13px; color: var(--muted); line-height: 1.5; margin-bottom: 10px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .card-footer { display: flex; align-items: center; gap: 12px; }
  .card-link { font-size: 12px; color: var(--accent); text-decoration: none; }
  .card-link:hover { text-decoration: underline; }
  .card-engagement { font-size: 12px; color: var(--muted); margin-left: auto; }

  .empty { text-align: center; padding: 60px 20px; color: var(--muted); }
  .empty-icon { font-size: 40px; margin-bottom: 12px; }
  .loading { text-align: center; padding: 20px; color: var(--muted); font-size: 13px; }

  /* Bilingual */
  .title-zh { font-size: 13px; color: var(--muted); margin-top: 3px; font-weight: 400; }
  .summary-block { margin: 8px 0 10px; }
  .summary-zh { font-size: 13px; color: var(--text); line-height: 1.6; margin-bottom: 4px; }
  .summary-en { font-size: 12px; color: var(--muted); line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }

  /* Daily briefing panel */
  .briefing-panel { background: linear-gradient(135deg, #0d1f2d 0%, #111a26 100%);
    border: 1px solid #1e3a5f; border-radius: 10px; padding: 16px 20px; margin-bottom: 16px; }
  .briefing-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
  .briefing-title { font-size: 13px; font-weight: 600; color: var(--accent); letter-spacing: .03em; }
  .briefing-meta { font-size: 11px; color: var(--muted); }
  .briefing-refresh { background: none; border: 1px solid var(--border); color: var(--muted);
    font-size: 11px; padding: 3px 8px; border-radius: 4px; cursor: pointer; }
  .briefing-refresh:hover { border-color: var(--accent); color: var(--accent); }
  .briefing-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
  @media (max-width: 1200px) { .briefing-grid { grid-template-columns: repeat(3, 1fr); } }
  @media (max-width: 800px)  { .briefing-grid { grid-template-columns: 1fr 1fr; } }
  .briefing-section { background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.07);
    border-radius: 8px; padding: 12px 14px; }
  .briefing-section-title { font-size: 12px; font-weight: 700; color: var(--text);
    margin-bottom: 10px; display: flex; align-items: center; gap: 6px; }
  .briefing-points { list-style: none; padding: 0; margin: 0; }
  .briefing-points li { font-size: 12px; color: #b0bec5; line-height: 1.55;
    padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,.05); }
  .briefing-points li:last-child { border-bottom: none; }
  .briefing-points li::before { content: "·"; margin-right: 6px; color: var(--accent); font-weight: 700; }
  .briefing-loading { font-size: 13px; color: var(--muted); font-style: italic; padding: 8px 0; }

  /* Digest summary panel */
  .digest-panel { background: linear-gradient(135deg, #1a2332 0%, #162032 100%);
    border: 1px solid #2d4a6e; border-radius: 10px; padding: 16px 20px; margin-bottom: 16px; }
  .digest-panel-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
  .digest-panel-title { font-size: 13px; font-weight: 600; color: var(--accent); }
  .digest-refresh { background: none; border: 1px solid var(--border); color: var(--muted);
    font-size: 11px; padding: 3px 8px; border-radius: 4px; cursor: pointer; }
  .digest-refresh:hover { border-color: var(--accent); color: var(--accent); }
  .digest-text { font-size: 14px; color: var(--text); line-height: 1.8; }
  .digest-loading { font-size: 13px; color: var(--muted); font-style: italic; }
</style>
</head>
<body>
<div class="layout">
  <!-- Sidebar -->
  <aside class="sidebar">
    <div class="sidebar-header">
      <h1><span class="status-dot" id="statusDot"></span>AI News Monitor</h1>
      <div class="sub" id="statusText">Connecting…</div>
    </div>
    <div class="sidebar-section">Filter</div>
    <button class="filter-btn active" onclick="setFilter('all')">🌐 All Sources <span class="count" id="cnt-all">0</span></button>
    <button class="filter-btn" onclick="setFilter('posts')">📰 Blog Posts <span class="count" id="cnt-posts">0</span></button>
    <button class="filter-btn" onclick="setFilter('tweets')">𝕏 Posts <span class="count" id="cnt-tweets">0</span></button>
    <div class="sidebar-section" style="margin-top:8px;">Top Sources</div>
    <div id="sourceList"></div>
    <div class="stats-box">
      <div class="stat-row"><span class="stat-label">Posts in DB</span><span class="stat-val" id="statPosts">—</span></div>
      <div class="stat-row"><span class="stat-label">X Posts in DB</span><span class="stat-val" id="statTweets">—</span></div>
      <div class="stat-row"><span class="stat-label">Last update</span><span class="stat-val" id="statLast">—</span></div>
    </div>
  </aside>

  <!-- Main -->
  <div class="main">
    <div class="topbar">
      <div class="search-wrap">
        <span class="search-icon">🔍</span>
        <input type="text" id="searchInput" placeholder="Search news…" oninput="onSearch(this.value)">
      </div>
      <span class="new-badge" id="newBadge" onclick="scrollToTop()">↑ New items</span>
    </div>
    <div class="feed" id="feed">
      <!-- Daily briefing -->
      <div class="briefing-panel" id="briefingPanel">
        <div class="briefing-header">
          <span class="briefing-title">⚡ 每日要闻速报</span>
          <div style="display:flex;align-items:center;gap:10px;">
            <span class="briefing-meta" id="briefingMeta"></span>
            <button class="briefing-refresh" onclick="loadBriefing()">↻ 刷新</button>
          </div>
        </div>
        <div id="briefingBody"><span class="briefing-loading">正在生成速报…</span></div>
      </div>
      <!-- Digest summary -->
      <div class="digest-panel" id="digestPanel">
        <div class="digest-panel-header">
          <span class="digest-panel-title">📋 今日 AI 资讯摘要</span>
          <button class="digest-refresh" onclick="loadDigest()">↻ 刷新</button>
        </div>
        <div class="digest-text" id="digestText"><span class="digest-loading">正在生成摘要…</span></div>
      </div>
      <div id="cardFeed"><div class="loading">Loading…</div></div>
    </div>
  </div>
</div>

<script>
let allItems = [];
let currentFilter = 'all';
let ws;

// ── WebSocket ──────────────────────────────────────────────────────────────
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    document.getElementById('statusDot').style.background = 'var(--green)';
    document.getElementById('statusText').textContent = 'Live';
  };
  ws.onclose = () => {
    document.getElementById('statusDot').style.background = 'var(--red)';
    document.getElementById('statusText').textContent = 'Reconnecting…';
    setTimeout(connectWS, 3000);
  };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    const item = { type: msg.type, date: msg.data.created_at || msg.data.published || '', data: msg.data };
    allItems.unshift(item);
    updateCounts();
    if (currentFilter === 'all' || currentFilter === msg.type + 's') {
      prependCard(item, true);
      showNewBadge();
    }
    updateStats();
  };
}

// ── Load initial data ──────────────────────────────────────────────────────
async function loadNews() {
  const res = await fetch('/api/news?limit=50');
  allItems = await res.json();
  renderFeed();
  updateCounts();
  updateStats();
}

async function updateStats() {
  const s = await fetch('/api/stats').then(r => r.json());
  document.getElementById('statPosts').textContent = s.post_count.toLocaleString();
  document.getElementById('statTweets').textContent = s.tweet_count.toLocaleString();
  const last = s.latest_post_at || s.latest_tweet_at;
  document.getElementById('statLast').textContent = last ? last.slice(0,16).replace('T',' ') : '—';
}

// ── Render ─────────────────────────────────────────────────────────────────
function renderFeed() {
  const feed = document.getElementById('cardFeed');
  const filtered = filterItems(allItems);
  if (!filtered.length) {
    feed.innerHTML = '<div class="empty"><div class="empty-icon">📭</div>No items yet — monitor is fetching…</div>';
    return;
  }
  feed.innerHTML = '';
  filtered.forEach(item => feed.appendChild(makeCard(item, false)));
  buildSourceList();
}

function prependCard(item, isNew) {
  const feed = document.getElementById('cardFeed');
  const emptyEl = feed.querySelector('.empty, .loading');
  if (emptyEl) emptyEl.remove();
  feed.insertBefore(makeCard(item, isNew), feed.firstChild);
}

function makeCard(item, isNew) {
  const d = item.data;
  const isPost = item.type === 'post';
  const date = (d.created_at || d.published || '').slice(0,16).replace('T',' ');
  const tier = d.feed_priority === 1 ? '<span class="source-tag tag-tier1">T1</span>' : '';

  const div = document.createElement('div');
  div.className = 'card' + (isNew ? ' new-item' : '');

  if (isPost) {
    const zhTitle = d.title_zh ? `<div class="title-zh">${d.title_zh}</div>` : '';
    const summaryBlock = (d.summary || d.summary_zh) ? `
      <div class="summary-block">
        ${d.summary_zh ? `<div class="summary-zh">${d.summary_zh}</div>` : ''}
        ${d.summary    ? `<div class="summary-en">${d.summary}</div>` : ''}
      </div>` : '';
    div.innerHTML = `
      <div class="card-meta">
        <span class="source-tag tag-post">📰 ${d.source}</span>
        ${tier}
        <span class="card-date">${date}</span>
      </div>
      <div class="card-title">
        <a href="${d.url}" target="_blank">${d.title}</a>
        ${zhTitle}
      </div>
      ${summaryBlock}
      <div class="card-footer">
        <a href="${d.url}" target="_blank" class="card-link">Read article →</a>
      </div>`;
  } else {
    div.innerHTML = `
      <div class="card-meta">
        <span class="source-tag tag-tweet">𝕏 @${d.username}</span>
        ${d.category ? `<span class="source-tag" style="background:rgba(255,255,255,.08);color:var(--muted)">${d.category}</span>` : ''}
        <span class="card-date">${date}</span>
      </div>
      <div class="card-title" style="font-weight:400;font-size:14px;">${d.text}</div>
      <div class="card-footer">
        <a href="${d.url}" target="_blank" class="card-link">View tweet →</a>
        <span class="card-engagement">❤ ${d.likes||0} &nbsp; 🔁 ${d.retweets||0}</span>
      </div>`;
  }
  return div;
}

// ── Filters ────────────────────────────────────────────────────────────────
function filterItems(items) {
  if (currentFilter === 'posts')  return items.filter(i => i.type === 'post');
  if (currentFilter === 'tweets') return items.filter(i => i.type === 'tweet');
  return items;
}

function setFilter(f) {
  currentFilter = f;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  event.target.closest('.filter-btn').classList.add('active');
  renderFeed();
}

function updateCounts() {
  document.getElementById('cnt-all').textContent    = allItems.length;
  document.getElementById('cnt-posts').textContent  = allItems.filter(i=>i.type==='post').length;
  document.getElementById('cnt-tweets').textContent = allItems.filter(i=>i.type==='tweet').length;
}

function buildSourceList() {
  const counts = {};
  allItems.filter(i=>i.type==='post').forEach(i => {
    counts[i.data.source] = (counts[i.data.source]||0)+1;
  });
  const top = Object.entries(counts).sort((a,b)=>b[1]-a[1]).slice(0,6);
  const el = document.getElementById('sourceList');
  el.innerHTML = top.map(([src,cnt]) =>
    `<button class="filter-btn" style="font-size:12px;" onclick="filterSource('${src}')">${src} <span class="count">${cnt}</span></button>`
  ).join('');
}

function filterSource(src) {
  const filtered = allItems.filter(i => i.data.source === src);
  const feed = document.getElementById('cardFeed');
  feed.innerHTML = '';
  filtered.forEach(item => feed.appendChild(makeCard(item, false)));
}

async function loadBriefing() {
  const body = document.getElementById('briefingBody');
  const meta = document.getElementById('briefingMeta');
  body.textContent = '正在生成速报…';
  try {
    const res = await fetch('/api/briefing');
    const data = await res.json();
    const sections = data.sections || [];
    if (!sections.length) { body.textContent = '暂无数据'; return; }

    const grid = document.createElement('div');
    grid.className = 'briefing-grid';
    sections.forEach(s => {
      const sec = document.createElement('div');
      sec.className = 'briefing-section';

      const title = document.createElement('div');
      title.className = 'briefing-section-title';
      title.textContent = (s.icon || '') + ' ' + (s.label || s.category);
      sec.appendChild(title);

      const ul = document.createElement('ul');
      ul.className = 'briefing-points';
      (s.points || []).forEach(p => {
        const li = document.createElement('li');
        li.textContent = p;
        ul.appendChild(li);
      });
      sec.appendChild(ul);
      grid.appendChild(sec);
    });

    body.textContent = '';
    body.appendChild(grid);
    meta.textContent = new Date().toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit'}) + ' 更新';
  } catch (e) {
    body.textContent = '速报生成失败，请稍后重试';
  }
}

async function loadDigest() {
  const el = document.getElementById('digestText');
  el.innerHTML = '<span class="digest-loading">正在生成摘要…</span>';
  try {
    const res = await fetch('/api/digest-summary');
    const data = await res.json();
    el.textContent = data.summary || '暂无摘要';
  } catch (e) {
    el.textContent = '摘要生成失败，请稍后重试';
  }
}

// ── Search ─────────────────────────────────────────────────────────────────
let searchTimer;
async function onSearch(q) {
  clearTimeout(searchTimer);
  if (!q.trim()) { renderFeed(); return; }
  searchTimer = setTimeout(async () => {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=30`);
    const results = await res.json();
    const feed = document.getElementById('cardFeed');
    feed.innerHTML = '';
    if (!results.length) {
      feed.innerHTML = `<div class="empty"><div class="empty-icon">🔍</div>No results for "${q}"</div>`;
      return;
    }
    results.forEach(r => {
      const isPost = !r.text;
      const item = { type: isPost?'post':'tweet', date: r.created_at||r.published||'', data: r };
      feed.appendChild(makeCard(item, false));
    });
  }, 300);
}

// ── Helpers ────────────────────────────────────────────────────────────────
function showNewBadge() {
  const badge = document.getElementById('newBadge');
  badge.classList.add('show');
  setTimeout(() => badge.classList.remove('show'), 5000);
}
function scrollToTop() {
  document.getElementById('feed').scrollTo({ top: 0, behavior: 'smooth' });
  document.getElementById('newBadge').classList.remove('show');
}

// ── Init ───────────────────────────────────────────────────────────────────
loadNews();
connectWS();
loadBriefing();
loadDigest();
setInterval(updateStats, 60000);
setInterval(loadBriefing, 30 * 60 * 1000);  // auto-refresh briefing every 30 min
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)
