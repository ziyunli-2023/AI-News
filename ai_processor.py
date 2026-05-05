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


def generate_daily_briefing(posts_by_category: dict) -> dict:
    """
    Generate a structured daily briefing with bullet points per category.
    Input: {category: [post_dicts]} from storage.get_recent_posts_by_category()
    Returns: {"sections": [{"category": str, "label": str, "icon": str, "points": [str]}]}
    """
    if not config.DEEPSEEK_API_KEY:
        return {"sections": []}

    CATEGORY_META = {
        "ai":       {"label": "AI 前沿",  "icon": "🤖"},
        "papers":   {"label": "AI 论文",  "icon": "📄"},
        "web3":     {"label": "Web3",     "icon": "⛓️"},
        "venture":  {"label": "创投圈",   "icon": "💰"},
        "us_stock": {"label": "美股",     "icon": "🇺🇸"},
    }

    # Build news text per category
    sections_input = []
    for cat, meta in CATEGORY_META.items():
        posts = posts_by_category.get(cat, [])
        if not posts:
            sections_input.append(f"【{meta['label']}】暂无数据")
            continue
        lines = [f"【{meta['label']}】"]
        for p in posts[:8]:
            lines.append(f"- {p.get('title_zh') or p.get('title', '')}")
        sections_input.append("\n".join(lines))

    news_text = "\n\n".join(sections_input)

    prompt = f"""以下是今日各板块的最新资讯标题：

{news_text}

请为每个板块生成 3~4 条要点，要求：
- 每条要点 30 字以内，简洁直接
- 重点突出具体事件、数字、名称
- 没有数据的板块输出"暂无重要动态"
- 严格按以下 JSON 格式返回，不要添加其他内容：

{{"sections": [
  {{"category": "ai",       "points": ["...", "...", "..."]}},
  {{"category": "papers",   "points": ["...", "...", "..."]}},
  {{"category": "web3",     "points": ["...", "...", "..."]}},
  {{"category": "venture",  "points": ["...", "...", "..."]}},
  {{"category": "us_stock", "points": ["...", "...", "..."]}}
]}}"""

    try:
        resp = _get_client().chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.4,
        )
        raw = resp.choices[0].message.content.strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("No JSON object in response")
        data = json.loads(raw[start:end + 1])
        # Attach label/icon metadata
        for sec in data.get("sections", []):
            meta = CATEGORY_META.get(sec["category"], {})
            sec["label"] = meta.get("label", sec["category"])
            sec["icon"] = meta.get("icon", "📌")
        return data
    except Exception as e:
        logger.error("generate_daily_briefing failed: %s", e)
        return {"sections": []}


def generate_digest_summary(items: list[dict]) -> list[str]:
    """
    Generate a bullet-point Chinese digest of a batch of news items.
    Input: list of {"type": "post"|"tweet", "item"|"data": {...}} dicts.
    Returns: list of short Chinese bullets (3-6 points), or [] on failure.
    """
    if not config.DEEPSEEK_API_KEY or not items:
        return []

    lines = []
    for item in items[:30]:
        # Support both wrapper shapes: notifier uses "item", web_server uses "data"
        d = item.get("item") or item.get("data") or item
        if item.get("type") == "tweet":
            lines.append(f"- [Tweet @{d.get('username','')}] {d.get('text','')[:100]}")
        else:
            lines.append(f"- [{d.get('source','')}] {d.get('title','')}")
    news_list = "\n".join(lines)

    prompt = f"""以下是今天的AI资讯列表：

{news_list}

请用简体中文提炼出 3-6 个最重要的看点，每个看点一行，独立成条，语言简洁专业。
要求：
- 每条 30 字以内
- 每条聚焦一个具体进展/话题，不要泛泛而谈
- 严格按以下 JSON 数组格式返回，不要任何额外文字：
["看点1", "看点2", "看点3"]"""

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
        bullets = json.loads(raw[start:end + 1])
        return [str(b).strip() for b in bullets if str(b).strip()]
    except Exception as e:
        logger.error("generate_digest_summary failed: %s", e)
        return []
