"""AI processor — translation (EN→ZH) and digest summarization via DeepSeek API."""

import json
import logging

from openai import OpenAI

import config

logger = logging.getLogger(__name__)

_client: OpenAI = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
        )
    return _client


def _extract_json_array(raw: str):
    raw = (raw or "").strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("No JSON array in response")
    return json.loads(raw[start:end + 1])


def translate_batch(posts: list[dict]) -> list[dict]:
    """
    Translate up to 5 posts per call.
    Input: list of dicts with 'title' and 'summary' keys.
    Returns: list of dicts with 'title_zh' and 'summary_zh' keys.
    """
    if not config.DEEPSEEK_API_KEY or not posts:
        return posts  # Return original posts so caller can use title/summary

    items_text = "\n".join(
        f"{i+1}. title: {p.get('title','')}\n   summary: {p.get('summary','')[:300]}"
        for i, p in enumerate(posts[:5])
    )

    prompt = f"""你是AI领域专业翻译。将以下英文AI资讯的标题和摘要翻译成简体中文。
技术术语规则：LLM、RLHF、fine-tuning、prompt、transformer、token、benchmark 等保留英文或使用业界通用译法。

{items_text}

严格按以下 JSON 数组格式返回，不要添加任何其他内容：
[{{"title_zh": "...", "summary_zh": "..."}}, ...]"""

    try:
        resp = _get_client().chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content.strip()
        results = _extract_json_array(raw)
        while len(results) < len(posts):
            results.append({})
        return results[:len(posts)]
    except Exception as e:
        logger.error("translate_batch failed: %s", e)
        return posts  # Return original posts on failure for graceful fallback


def _translate_texts_once(texts: list[str]) -> list[str]:
    """
    Single-pass batch translation. Returns originals for any slot that fails.
    """
    indexed = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
    if not indexed:
        return list(texts)

    items_text = "\n".join(f"{n+1}. {t[:500]}" for n, (_, t) in enumerate(indexed))
    prompt = f"""你是AI/科技领域专业翻译。将下面编号的英文内容逐条翻译成简体中文。
技术术语规则：LLM、RLHF、fine-tuning、prompt、transformer、token、benchmark 等保留英文或使用业界通用译法。
保持简洁、忠实原文，不要添加解释。

{items_text}

严格按以下 JSON 数组格式返回，按相同顺序，长度必须为 {len(indexed)}，不要添加任何其他内容：
["译文1", "译文2", ...]"""

    out = list(texts)
    try:
        resp = _get_client().chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content.strip()
        results = _extract_json_array(raw)
        for (orig_idx, _), translated in zip(indexed, results):
            if isinstance(translated, str) and translated.strip():
                out[orig_idx] = translated.strip()
    except Exception as e:
        raise ValueError(str(e)) from e
    return out


def translate_texts(texts: list[str]) -> list[str]:
    """
    On-demand translator for arbitrary English snippets → simplified Chinese.
    Used for post titles/summaries and tweet text when the background worker
    hasn't translated them yet. Returns a list of the same length; on failure
    or empty input the original text is returned for that slot.
    """
    if not config.DEEPSEEK_API_KEY or not texts:
        return list(texts)

    try:
        return _translate_texts_once(texts)
    except Exception as e:
        logger.error("translate_texts failed for batch size %d: %s", len(texts), e)
        if len(texts) <= 1:
            return list(texts)

        mid = len(texts) // 2
        left = translate_texts(texts[:mid])
        right = translate_texts(texts[mid:])
        return left + right


def generate_daily_briefing(posts_by_category: dict, lang: str = "zh") -> dict:
    """
    Generate a structured daily briefing with bullet points per category.
    Input: {category: [post_dicts]} from storage.get_recent_posts_by_category()
    Returns: {"sections": [{"category": str, "label": str, "icon": str, "points": [str]}]}
    """
    if not config.DEEPSEEK_API_KEY:
        return {"sections": []}

    CATEGORY_META = {
        "zh": {
            "polymarket":  {"label": "预测市场", "icon": "🎯"},
            "us_stock":    {"label": "美股",     "icon": "🇺🇸"},
            "ai":          {"label": "AI 前沿",  "icon": "🤖"},
            "papers":      {"label": "AI 论文",  "icon": "📄"},
            "web3":        {"label": "Web3",     "icon": "⛓️"},
            "venture":     {"label": "创投圈",   "icon": "💰"},
        },
        "en": {
            "polymarket":  {"label": "Prediction Markets","icon": "🎯"},
            "us_stock":    {"label": "US Stocks",        "icon": "🇺🇸"},
            "ai":          {"label": "AI",               "icon": "🤖"},
            "papers":      {"label": "Papers",           "icon": "📄"},
            "web3":        {"label": "Web3",             "icon": "⛓️"},
            "venture":     {"label": "Venture",          "icon": "💰"},
        },
    }
    meta_map = CATEGORY_META.get(lang, CATEGORY_META["zh"])

    # Build news text per category — pass all candidates, let AI pick the best
    sections_input = []
    for cat, meta in meta_map.items():
        posts = posts_by_category.get(cat, [])
        if not posts:
            no_data = "No data" if lang == "en" else "暂无数据"
            sections_input.append(f"[{meta['label']}] {no_data}")
            continue
        lines = [f"[{meta['label']}]"]
        for i, p in enumerate(posts):
            if cat == "polymarket":
                summary = (p.get("summary") or "").split(" | Ends")[0]
                lines.append(f"{i+1}. {p.get('title', '')} ({summary})")
            else:
                title = p.get("title") if lang == "en" else (p.get("title_zh") or p.get("title", ""))
                source = p.get("source", "")
                lines.append(f"{i+1}. [{source}] {title}")
        sections_input.append("\n".join(lines))

    news_text = "\n\n".join(sections_input)

    # Build a flat url_map: cat -> {1-based index -> url}
    url_map: dict[str, dict[int, str]] = {}
    for cat, posts in posts_by_category.items():
        url_map[cat] = {i + 1: p.get("url", "") for i, p in enumerate(posts)}

    if lang == "en":
        prompt = f"""The following are today's news candidates by category (more than needed — you must select the most important ones):

{news_text}

Your task: For each category, SELECT the 4-5 most newsworthy items and write a punchy bullet for each.
Selection criteria: global impact, specific numbers/names, market-moving events, breakthroughs — NOT routine updates or minor news.
Requirements:
- Each bullet under 20 words, direct and specific
- Must reference the actual event, company, or number — no vague summaries
- For categories with no data, use src 0 and text "No major updates"
- Return strictly in this JSON format, no extra content:

{{"sections": [
  {{"category": "polymarket",  "points": [{{"text": "...", "src": 1}}, {{"text": "...", "src": 3}}]}},
  {{"category": "us_stock",    "points": [{{"text": "...", "src": 2}}, {{"text": "...", "src": 4}}]}},
  {{"category": "ai",          "points": [{{"text": "...", "src": 1}}, {{"text": "...", "src": 5}}]}},
  {{"category": "papers",      "points": [{{"text": "...", "src": 2}}, {{"text": "...", "src": 3}}]}},
  {{"category": "web3",        "points": [{{"text": "...", "src": 1}}, {{"text": "...", "src": 4}}]}},
  {{"category": "venture",     "points": [{{"text": "...", "src": 2}}, {{"text": "...", "src": 6}}]}}
]}}"""
    else:
        prompt = f"""以下是今日各板块的候选资讯（数量超出需要，你需要主动挑选最重要的）：

{news_text}

你的任务：每个板块从候选项中挑出 4~5 条最值得关注的，写成简洁有力的速报要点。
挑选标准：全球影响力、具体数字/事件/人名、市场震动、重大突破——日常更新、常规动态不选。
写作要求：
- 每条 35 字以内，直接点名事件、数字、公司
- 预测市场：必须给出概率和成交量，用"市场押注"、"赔率显示"等措辞，体现分歧与戏剧性
- 美股/创投：突出涨跌幅、融资金额、具体公司名
- AI：突出产品发布、能力突破、重大合作
- 没有数据的板块用 src 0，text 填"暂无重要动态"
- 严格按以下 JSON 格式返回，不要添加其他内容：

{{"sections": [
  {{"category": "polymarket",  "points": [{{"text": "...", "src": 1}}, {{"text": "...", "src": 3}}]}},
  {{"category": "us_stock",    "points": [{{"text": "...", "src": 2}}, {{"text": "...", "src": 4}}]}},
  {{"category": "ai",          "points": [{{"text": "...", "src": 1}}, {{"text": "...", "src": 5}}]}},
  {{"category": "papers",      "points": [{{"text": "...", "src": 2}}, {{"text": "...", "src": 3}}]}},
  {{"category": "web3",        "points": [{{"text": "...", "src": 1}}, {{"text": "...", "src": 4}}]}},
  {{"category": "venture",     "points": [{{"text": "...", "src": 2}}, {{"text": "...", "src": 6}}]}}
]}}"""

    try:
        resp = _get_client().chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
            temperature=0.6,
        )
        raw = resp.choices[0].message.content.strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("No JSON object in response")
        data = json.loads(raw[start:end + 1])
        # Attach label/icon metadata and resolve src index -> url
        for sec in data.get("sections", []):
            cat = sec.get("category", "")
            meta = meta_map.get(cat, {})
            sec["label"] = meta.get("label", cat)
            sec["icon"] = meta.get("icon", "📌")
            cat_urls = url_map.get(cat, {})
            resolved = []
            for pt in sec.get("points", []):
                if isinstance(pt, dict):
                    url = cat_urls.get(int(pt.get("src") or 0), "") or ""
                    resolved.append({"text": pt.get("text", ""), "url": url})
                else:
                    resolved.append({"text": str(pt), "url": ""})
            sec["points"] = resolved
        return data
    except Exception as e:
        logger.error("generate_daily_briefing failed: %s", e)
        return {"sections": []}


def generate_digest_summary(items: list[dict], lang: str = "zh") -> list[str]:
    """
    Generate a bullet-point digest of a batch of news items.
    Input: list of {"type": "post"|"tweet", "item"|"data": {...}} dicts.
    Returns: list of short bullets (3-6 points), or [] on failure.
    """
    if not config.DEEPSEEK_API_KEY or not items:
        return []

    candidates = items[:30]
    url_index: dict[int, str] = {}
    lines = []
    for i, item in enumerate(candidates):
        d = item.get("item") or item.get("data") or item
        url_index[i + 1] = d.get("url", "")
        if item.get("type") == "tweet":
            lines.append(f"{i+1}. [Tweet @{d.get('username','')}] {d.get('text','')[:100]}")
        else:
            lines.append(f"{i+1}. [{d.get('source','')}] {d.get('title','')}")
    news_list = "\n".join(lines)

    if lang == "en":
        prompt = f"""The following is today's news list (numbered):

{news_list}

Extract 3-6 key highlights. Requirements:
- Each point under 20 words, specific and direct
- Return strictly as a JSON array with text and source index, no extra text:
[{{"text": "highlight1", "src": 2}}, {{"text": "highlight2", "src": 5}}]"""
    else:
        prompt = f"""以下是今天的资讯列表（已编号）：

{news_list}

请提炼出 3~6 个最重要的看点，每条 30 字以内，聚焦具体事件，不要泛泛而谈。
严格按以下 JSON 数组格式返回，不要任何额外文字：
[{{"text": "看点1", "src": 2}}, {{"text": "看点2", "src": 5}}]"""

    try:
        resp = _get_client().chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.5,
        )
        raw = resp.choices[0].message.content.strip()
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            raise ValueError("No JSON array in response")
        parsed = json.loads(raw[start:end + 1])
        result = []
        for b in parsed:
            if isinstance(b, dict):
                text = str(b.get("text", "")).strip()
                url = url_index.get(int(b.get("src") or 0), "") or ""
            else:
                text = str(b).strip()
                url = ""
            if text:
                result.append({"text": text, "url": url})
        return result
    except Exception as e:
        logger.error("generate_digest_summary failed: %s", e)
        return []
