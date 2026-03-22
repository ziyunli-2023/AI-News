# AI News Monitor — 完整系统计划

## 背景与目标

搭建一个自动化 AI 资讯监控系统，实时追踪 X（Twitter）上的 AI 大咖动态和主要 AI 博客/Newsletter，存入 SQLite，通过 MCP 服务器暴露给 Claude Code 查询。

**当前状态**：`/Users/ziyun/Documents/Code/News/` 下已有基础骨架（config、monitors、storage、mcp_server），但存在若干关键 Bug，系统尚不可用。

---

## 一、追踪的 X 账号（29个）

按优先级分3档：

- **Priority 1**：核心人物，绝不能漏
- **Priority 2**：重要，正常追踪
- **Priority 3**：信噪比低，加 AI 关键词过滤后再入库

| Handle | 姓名 | 类别 | 优先级 |
|---|---|---|---|
| karpathy | Andrej Karpathy | researcher | 1 |
| DarioAmodei | Dario Amodei | founder | 1 |
| sama | Sam Altman | founder | 1 |
| ilyasut | Ilya Sutskever | researcher | 1 |
| fchollet | François Chollet | researcher | 1 |
| ch402 | Chris Olah | researcher | 1 |
| Thom_Wolf | Thomas Wolf | researcher | 1 |
| natolambert | Nathan Lambert | researcher | 1 |
| demishassabis | Demis Hassabis | founder | 2 |
| gdb | Greg Brockman | founder | 2 |
| AravSrinivas | Aravind Srinivas | founder | 2 |
| JeffDean | Jeff Dean | researcher | 2 |
| soumithchintala | Soumith Chintala | researcher | 2 |
| DrJimFan | Jim Fan | researcher | 2 |
| jackclarkSF | Jack Clark | researcher | 2 |
| OfficialLoganK | Logan Kilpatrick | practitioner | 2 |
| paulfchristiano | Paul Christiano | safety | 2 |
| tegmark | Max Tegmark | safety | 2 |
| AndrewYNg | Andrew Ng | academic | 2 |
| drfeifei | Fei-Fei Li | academic | 2 |
| rasbt | Sebastian Raschka | academic | 2 |
| emollick | Ethan Mollick | academic | 2 |
| chipro | Chip Huyen | practitioner | 2 |
| alliekmiller | Allie K. Miller | practitioner | 2 |
| lexfridman | Lex Fridman | practitioner | 2 |
| ylecun | Yann LeCun | researcher | 3 |
| GaryMarcus | Gary Marcus | academic | 3 |
| ESYudkowsky | Eliezer Yudkowsky | safety | 3 |
| rowancheung | Rowan Cheung | practitioner | 3 |

### X API 档位说明

| 档位 | 价格 | 限速 | 适配方案 |
|---|---|---|---|
| Free | $0 | 1次/15分钟（全局） | 只追踪 Priority 1（8人），轮询间隔 30 分钟 |
| Basic | $100/月 | 15次/15分钟 | 全部 29 人，轮询间隔 30 分钟 |

> ✅ **已确认**：使用 Free 档，只追 Priority 1 的 8 个核心账号，其余 AI 动态靠 RSS 补充覆盖。

---

## 二、RSS 订阅源（22个）

### Tier 1 — 实验室博客 + 深度 Newsletter（每 30 分钟轮询）

| 名称 | RSS URL |
|---|---|
| OpenAI | `https://openai.com/news/rss.xml` |
| Anthropic | `https://raw.githubusercontent.com/0xSMW/rss-feeds/main/feeds/feed_anthropic_news.xml` |
| Google DeepMind | `https://deepmind.google/blog/rss.xml` |
| Hugging Face | `https://huggingface.co/blog/feed.xml` |
| Import AI | `https://importai.substack.com/feed` |
| Interconnects | `https://www.interconnects.ai/feed` |
| Ahead of AI | `https://magazine.sebastianraschka.com/feed` |
| The Batch | `https://www.deeplearning.ai/the-batch/feed.xml` |

### Tier 2 — 研究 & 行业博客（每 60 分钟轮询）

| 名称 | RSS URL |
|---|---|
| Google AI Blog | `https://blog.google/technology/ai/rss/` |
| Google Research | `https://research.google/blog/rss/` |
| AWS ML Blog | `https://aws.amazon.com/blogs/machine-learning/feed/` |
| BAIR Blog | `https://bair.berkeley.edu/blog/feed.xml` |
| Last Week in AI | `https://lastweekin.ai/feed` |
| Marcus on AI | `https://garymarcus.substack.com/feed` |
| Chollet Substack | `https://fchollet.substack.com/feed` |
| The Decoder | `https://the-decoder.com/feed/` |

### Tier 3 — 科技媒体（每 2 小时轮询，加关键词过滤）

| 名称 | RSS URL |
|---|---|
| VentureBeat AI | `https://venturebeat.com/category/ai/feed/` |
| The Verge AI | `https://www.theverge.com/rss/ai-artificial-intelligence/index.xml` |
| Wired AI | `https://www.wired.com/feed/tag/ai/latest/rss` |
| Towards Data Science | `https://towardsdatascience.com/feed/` |

### ArXiv（独立处理，强制关键词过滤）

| 名称 | RSS URL |
|---|---|
| arXiv cs.AI | `http://arxiv.org/rss/cs.AI` |
| arXiv cs.LG | `http://arxiv.org/rss/cs.LG` |

ArXiv 每天发布 50~200+ 篇论文，必须只保留标题/摘要包含以下关键词的论文：
`language model`, `llm`, `alignment`, `reasoning`, `agent`, `rlhf`, `multimodal`, `instruction tuning`, `chain-of-thought`, `in-context learning`, `transformer`

---

## 三、系统架构

```
Claude Code (用户)
      │
      │ MCP stdio
      ▼
mcp_server.py ──── 10 个 MCP 工具
      │
      ├── XMonitor（后台线程）
      │     └── X API v2 / tweepy
      │
      ├── RSSMonitor（后台线程）
      │     └── httpx + feedparser
      │
      └── storage.py（SQLite: news.db）
            ├── tweets
            ├── blog_posts
            ├── x_cursors      ← 新增
            └── feed_health    ← 新增
```

---

## 四、必须修复的关键 Bug（Phase 1）

### Bug 1：`since_id` 未持久化
- **问题**：XMonitor 的 `_since_ids` 只在内存中，每次 MCP 服务器重启（即每次打开 Claude Code）就丢失，重新拉取所有用户最新 10 条推文，产生大量重复通知
- **修复**：新增 `x_cursors` 表，启动时读取，每次成功拉取后写入
- **文件**：`storage.py`、`x_monitor.py`

### Bug 2：`get_all_news` 分割逻辑错误
- **问题**：`half = limit // 2`，先从 tweets 和 posts 各取 15 条，再合并排序，导致如果有 20 条重要博文只能看到 15 条
- **修复**：改为各取 `limit * 2` 条，合并排序后截取 `limit`
- **文件**：`mcp_server.py`

### Bug 3：推文互动数不更新
- **问题**：`save_tweet` 用 `INSERT`，互动数（likes/retweets）在首次写入后永远不变
- **修复**：改为 `INSERT ... ON CONFLICT(id) DO UPDATE SET likes=excluded.likes, retweets=excluded.retweets`
- **文件**：`storage.py`

### Bug 4：ArXiv 无过滤
- **问题**：每 30 分钟存入 20 条 ArXiv 论文，一天 40+ 条，绝大多数与 AI 大方向无关
- **修复**：保存前检查标题/摘要是否含关键词，不含则跳过
- **文件**：`rss_monitor.py`

### Bug 5：RSS 摘要 HTML 实体未解码
- **问题**：`re.sub` 去掉标签后，`&amp;`、`&nbsp;`、`&#8220;` 等实体字符残留在摘要里
- **修复**：strip 标签后加 `html.unescape()`
- **文件**：`rss_monitor.py`

---

## 五、数据库 Schema 变更

### tweets 表 — 新增字段

```sql
reply_count   INTEGER DEFAULT 0   -- 回复数（争议性指标）
lang          TEXT                -- 语言代码，过滤非英文
priority_rank INTEGER DEFAULT 2   -- 来自 config 的账号优先级
category      TEXT                -- researcher/founder/safety/academic/practitioner
```

### blog_posts 表 — 新增字段

```sql
feed_priority INTEGER DEFAULT 2   -- RSS Tier 1/2/3
content_hash  TEXT                -- 标准化标题的 SHA-256，用于跨源去重
```

### 新增：x_cursors 表

```sql
CREATE TABLE IF NOT EXISTS x_cursors (
    user_id    TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    since_id   TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### 新增：feed_health 表

```sql
CREATE TABLE IF NOT EXISTS feed_health (
    source               TEXT PRIMARY KEY,
    last_success         TEXT,
    last_error           TEXT,
    consecutive_failures INTEGER DEFAULT 0
);
```

---

## 六、config.py 结构升级

账号列表改为字典列表：
```python
TRACKED_X_USERS = [
    {"username": "karpathy",   "priority": 1, "category": "researcher"},
    {"username": "DarioAmodei","priority": 1, "category": "founder"},
    # ...
]
```

RSS 列表改为：
```python
RSS_FEEDS = [
    {"name": "OpenAI", "url": "...", "tier": 1},
    # ...
]
```

新增常量：
```python
# Priority 3 X账号关键词过滤
X_NOISE_KEYWORDS = {
    "llm", "gpt", "claude", "gemini", "model", "paper", "research",
    "alignment", "safety", "agent", "benchmark", "rlhf", "training",
    "inference", "transformer", "multimodal", "reasoning", "openai",
    "anthropic", "deepmind"
}

# ArXiv 关键词过滤
ARXIV_KEYWORDS = {
    "language model", "llm", "alignment", "reasoning", "agent",
    "rlhf", "multimodal", "instruction tuning", "chain-of-thought",
    "in-context learning", "transformer", "fine-tuning"
}

# 各 Tier RSS 轮询间隔（秒）
RSS_POLL_INTERVALS = {1: 1800, 2: 3600, 3: 7200}
```

---

## 七、MCP 工具（现有 6 个 → 10 个）

### 现有工具（需修复）

| 工具 | 修复内容 |
|---|---|
| `get_all_news` | 修复 Bug 2（分割逻辑） |
| `get_new_since_last_check` | 改用 DB 游标而非内存列表，重启后不丢失 |

### 新增工具

| 工具 | 说明 | 参数 |
|---|---|---|
| `search_news` | 全文搜索推文+博文 | `query`, `limit`, `source_type` (tweets/posts/all) |
| `get_top_posts` | 按互动数排序（热门内容） | `hours` (默认48), `limit` |
| `get_health` | 监控器健康状态：最后轮询时间、失败的 feeds | 无 |
| `get_by_category` | 按账号类别过滤推文 | `category` (researcher/founder/safety/academic/practitioner) |

### 完整工具列表（实现后）

1. `get_latest_tweets` — 最新推文（支持按用户过滤）
2. `get_latest_blog_posts` — 最新博文（支持按源过滤）
3. `get_all_news` — 推文+博文混合流（修复后）
4. `get_new_since_last_check` — 上次查询后的新内容（DB游标版）
5. `get_stats` — 数据库统计
6. `list_tracked_sources` — 所有追踪源列表
7. `search_news` ← 新增
8. `get_top_posts` ← 新增
9. `get_health` ← 新增
10. `get_by_category` ← 新增

---

## 八、实施阶段

### Phase 1 — 修关键 Bug（系统能跑起来的前提）
- [ ] Bug 1：x_cursors 持久化（`storage.py` + `x_monitor.py`）
- [ ] Bug 2：get_all_news 分割逻辑（`mcp_server.py`）
- [ ] Bug 3：save_tweet UPSERT（`storage.py`）
- [ ] Bug 4：ArXiv 关键词过滤（`rss_monitor.py`）
- [ ] Bug 5：HTML 实体解码（`rss_monitor.py`）

### Phase 2 — 数据模型 & 配置升级
- [ ] config.py 改为带 priority/category/tier 的字典结构
- [ ] storage.py 添加新字段和新表，更新 `init_db()`
- [ ] x_monitor.py 传入 priority_rank、category、lang、reply_count
- [ ] rss_monitor.py 传入 feed_priority、content_hash，记录 feed_health

### Phase 3 — 新增 MCP 工具
- [ ] `search_news`
- [ ] `get_top_posts`
- [ ] `get_health`
- [ ] `get_by_category`
- [ ] 修复 `get_new_since_last_check`（DB游标）

### Phase 4 — 质量过滤
- [ ] X：Priority 3 账号关键词过滤
- [ ] X：lang 字段语言过滤（跳过非英文）
- [ ] RSS：跨源 content_hash 去重
- [ ] RSS：按 tier 分别设置轮询间隔

---

## 九、涉及文件

| 文件 | 修改内容 |
|---|---|
| `config.py` | 账号/feed 改为带元数据的字典，添加关键词常量和分级轮询间隔 |
| `storage.py` | schema 迁移、UPSERT、新表、新查询函数（search、top_posts、health） |
| `x_monitor.py` | 游标持久化、lang过滤、Priority 3 关键词过滤、请求 reply_count |
| `rss_monitor.py` | ArXiv过滤、HTML实体修复、feed_health 记录、content_hash、分级间隔 |
| `mcp_server.py` | 修复 get_all_news、修复 get_new_since_last_check、新增4个工具 |

---

## 十、验证方法

1. **启动测试**：`cd /Users/ziyun/Documents/Code/News && .venv/bin/python3.13 mcp_server.py`
   - 预期：打印 "Database initialised"、"X monitor started"、"RSS monitor started"，无报错

2. **RSS 测试**：等待 2 分钟，调用 `get_stats`
   - 预期：`post_count > 0`

3. **X 测试**：填好 `.env`，调用 `get_latest_tweets`
   - 预期：返回推文列表

4. **搜索测试**：`search_news query="GPT"`
   - 预期：返回含 "GPT" 的推文或博文

5. **健康检测**：`get_health`
   - 预期：显示最后轮询时间，failed_feeds 为空

6. **重启持久化测试**：重启服务后调用 `get_stats`
   - 预期：数据条数与重启前一致，不归零

---

## 待确认事项

- **X API 档位**：✅ Free 档，追 Priority 1 的 8 个账号，轮询间隔 30 分钟。
