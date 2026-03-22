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


def translate_batch(posts: list[dict]) -> list[dict]:
    """
    Translate up to 5 posts per call.
    Input: list of dicts with 'title' and 'summary' keys.
    Returns: list of dicts with 'title_zh' and 'summary_zh' keys.
    """
    if not config.DEEPSEEK_API_KEY or not posts:
        return [{}] * len(posts)

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
        start = raw.find("[")
        end   = raw.rfind("]") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON array in response")
        results = json.loads(raw[start:end])
        while len(results) < len(posts):
            results.append({})
        return results[:len(posts)]
    except Exception as e:
        logger.error("translate_batch failed: %s", e)
        return [{}] * len(posts)


def generate_digest_summary(items: list[dict]) -> str:
    """
    Generate a ~200-word Chinese summary of a batch of news items.
    Input: list of {"type": "post"|"tweet", "data": {...}} dicts.
    Returns: Chinese summary string, or "" on failure.
    """
    if not config.DEEPSEEK_API_KEY or not items:
        return ""

    lines = []
    for item in items[:30]:
        d = item.get("data", item)
        if item.get("type") == "tweet":
            lines.append(f"- [Tweet @{d.get('username','')}] {d.get('text','')[:100]}")
        else:
            lines.append(f"- [{d.get('source','')}] {d.get('title','')}")
    news_list = "\n".join(lines)

    prompt = f"""以下是今天的AI资讯列表：

{news_list}

请用200字以内的简体中文写一段综述，指出3个最重要的进展或话题，语言简洁专业。
直接输出段落，不要标题、不要序号。"""

    try:
        resp = _get_client().chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.5,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error("generate_digest_summary failed: %s", e)
        return ""
