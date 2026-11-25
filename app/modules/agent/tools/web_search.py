"""联网搜索工具（Tavily）：只对打开「联网」开关的那一轮提问生效。

边界（代码强制，不依赖提示词）：
- 默认不联网：``config.configurable["web_search"]`` 为假时工具不可用；图装配阶段也不会
  把该工具 bind 给模型，工具内部再做一次校验兜底。
- 密钥只在服务端读取（``TAVILY_API_KEY``），不接受模型传入 key、base_url 或结果条数上限。
- 只读外部网页信息，不接触用户个人数据；查询词长度受限，避免异常大请求。
- 外部结果只作为参考依据，平台数据仍以只读业务工具为准（口径见提示词）。
"""
from typing import Literal

import httpx
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from config import settings

WEB_SEARCH_TOOL_NAME = "web_search"
MIN_QUERY_CHARS = 2
MAX_QUERY_CHARS = 300
MAX_DAYS = 365
TOPIC_VALUES = ("general", "news")


def web_search_available() -> bool:
    """全局开关 + 密钥齐备时才对外提供联网能力。"""
    return bool(settings.web_search_enabled and (settings.tavily_api_key or "").strip())


def _flag_enabled(config: RunnableConfig | None) -> bool:
    return bool((config or {}).get("configurable", {}).get("web_search"))


async def _request_tavily(payload: dict) -> dict:
    """单次 POST 到 Tavily；单测可替换本函数，不真正联网。"""
    async with httpx.AsyncClient(timeout=settings.web_search_timeout_seconds) as client:
        response = await client.post(settings.tavily_search_url, json=payload)
        response.raise_for_status()
        data = response.json()
    return data if isinstance(data, dict) else {}


def _compact_results(data: dict) -> list[dict]:
    """只保留模型回答需要的字段，并按配置截断正文，避免整页原文进上下文。"""
    snippet_chars = max(200, settings.web_search_snippet_chars)
    items: list[dict] = []
    for raw in data.get("results") or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()[:200]
        url = str(raw.get("url") or "").strip()[:500]
        if not url:
            continue
        item = {
            "title": title or url,
            "url": url,
            "content": str(raw.get("content") or "").strip()[:snippet_chars],
        }
        published = str(raw.get("published_date") or "").strip()
        if published:
            item["published_date"] = published[:40]
        items.append(item)
    return items


async def search_web(
    query: str,
    *,
    topic: str = "general",
    days: int | None = None,
    enabled: bool = True,
) -> dict:
    """联网检索核心逻辑：参数清洗 → 调 Tavily → 收敛结果；不抛异常，失败返回结构化错误。"""
    if not enabled:
        return {"ok": False, "error": "本轮未开启联网搜索，请先在输入框打开「联网」后再试"}
    if not web_search_available():
        return {"ok": False, "error": "联网搜索未配置，请联系管理员在服务端配置搜索密钥"}

    text = (query or "").strip()
    if len(text) < MIN_QUERY_CHARS:
        return {"ok": False, "error": "检索关键词过短，请给出具体要查的内容"}
    text = text[:MAX_QUERY_CHARS]

    normalized_topic = topic if topic in TOPIC_VALUES else "general"
    payload: dict = {
        "api_key": settings.tavily_api_key.strip(),
        "query": text,
        "topic": normalized_topic,
        "search_depth": "basic",
        "max_results": max(1, min(10, settings.web_search_max_results)),
        "include_answer": False,
        "include_raw_content": False,
    }
    if normalized_topic == "news" and days is not None:
        try:
            day_count = int(days)
        except (TypeError, ValueError):
            return {"ok": False, "error": "days 需为正整数"}
        if not 1 <= day_count <= MAX_DAYS:
            return {"ok": False, "error": f"days 需在 1~{MAX_DAYS} 之间"}
        payload["days"] = day_count

    try:
        data = await _request_tavily(payload)
    except httpx.TimeoutException:
        return {"ok": False, "error": "联网搜索超时，请稍后重试"}
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else "未知"
        return {"ok": False, "error": f"联网搜索服务返回异常（{status}）"}
    except Exception:  # 网络、解析等异常统一收敛，模型可据此如实说明
        return {"ok": False, "error": "联网搜索暂时不可用，请稍后重试"}

    results = _compact_results(data)
    if not results:
        return {"ok": True, "query": text, "result_count": 0, "results": [],
                "note": "未检索到相关网页，请如实说明没有找到可靠信息"}
    return {"ok": True, "query": text, "result_count": len(results), "results": results}


@tool
async def web_search(
    query: str,
    topic: Literal["general", "news"] = "general",
    days: int | None = None,
    config: RunnableConfig = None,
) -> dict:
    """检索平台之外的最新网页与新闻，用于回答需要外部实时信息的问题。

    仅在「本轮已开启联网」时可用；平台内运动、身材、状态、周期、档案数据一律用业务只读工具，
    不要用本工具查询。query 写清楚要查的具体对象或事实（中英文均可）；topic=news 查最近新闻，
    可配合 days（最近 N 天，1~365）。返回结果含 title/url/content（可能含 published_date），
    回答时必须保留来源标题与链接，不得编造结果之外的事实或数字。
    """
    return await search_web(query, topic=topic, days=days, enabled=_flag_enabled(config))


__all__ = [
    "WEB_SEARCH_TOOL_NAME",
    "web_search",
    "search_web",
    "web_search_available",
]
