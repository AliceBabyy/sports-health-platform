"""联网搜索（V2.13）：默认不联网、按轮开关、密钥与结果边界。

Tavily 的真实 HTTP 调用统一替换为 ``_request_tavily`` 的桩，测试不访问外网。
"""
import asyncio

import httpx
import pytest

from app.modules.agent.graph import WEB_SEARCH_CAPABILITY, default_capabilities
from app.modules.agent.schemas import ContinueIn, MessageIn, RegenerateIn
from app.modules.agent.tools.web_search import (
    web_search,
    web_search_available,
    search_web,
)

KEY = "tvly-test-key"


@pytest.fixture(autouse=True)
def _enable_web(monkeypatch):
    monkeypatch.setattr("config.settings.web_search_enabled", True)
    monkeypatch.setattr("config.settings.tavily_api_key", KEY)


def test_request_schemas_default_to_offline():
    assert MessageIn(content="今天天气如何", client_msg_id="c1").web_search is False
    assert MessageIn(content="今天天气如何", client_msg_id="c1", web_search=True).web_search is True
    assert RegenerateIn(client_msg_id="c1").web_search is False
    assert ContinueIn(client_msg_id="c1").web_search is False


def test_availability_requires_key(monkeypatch):
    assert web_search_available() is True
    monkeypatch.setattr("config.settings.tavily_api_key", "")
    assert web_search_available() is False
    monkeypatch.setattr("config.settings.web_search_enabled", False)
    monkeypatch.setattr("config.settings.tavily_api_key", KEY)
    assert web_search_available() is False


def test_search_rejects_when_turn_switch_is_off():
    result = asyncio.run(search_web("马拉松 赛事结果", enabled=False))
    assert result["ok"] is False
    assert "未开启联网" in result["error"]


def test_search_rejects_without_key(monkeypatch):
    monkeypatch.setattr("config.settings.tavily_api_key", "")
    result = asyncio.run(search_web("马拉松 赛事结果"))
    assert result["ok"] is False
    assert "未配置" in result["error"]


def test_search_rejects_bad_days_and_short_query():
    assert asyncio.run(search_web("a"))["ok"] is False
    bad_days = asyncio.run(search_web("最近新闻", topic="news", days=0))
    assert bad_days["ok"] is False and "days" in bad_days["error"]
    too_long = asyncio.run(search_web("新闻", topic="news", days=1000))
    assert too_long["ok"] is False


def test_search_compacts_results(monkeypatch):
    captured = {}

    async def fake_request(payload):
        captured.update(payload)
        return {
            "results": [
                {"title": "赛事 A", "url": "https://example.com/a", "content": "x" * 1300,
                 "published_date": "2026-11-23T08:00:00"},
                {"title": "无链接", "content": "应被丢弃"},
                {"title": "", "url": "https://example.com/b", "content": "短内容"},
            ]
        }

    monkeypatch.setattr("app.modules.agent.tools.web_search._request_tavily", fake_request)
    result = asyncio.run(search_web(" 赛事结果 ", topic="news", days=7))

    assert result["ok"] is True
    assert result["query"] == "赛事结果"
    assert result["result_count"] == 2
    first, second = result["results"]
    assert first["title"] == "赛事 A"
    assert first["published_date"].startswith("2026-11-23")
    assert len(first["content"]) <= 1200
    # 标题为空时回退为链接本体，仍保留可用来源
    assert second["title"] == "https://example.com/b"
    assert captured["api_key"] == KEY
    assert captured["topic"] == "news" and captured["days"] == 7
    assert captured["max_results"] == 5
    assert captured["include_answer"] is False


def test_search_reports_empty_results(monkeypatch):
    async def fake_request(payload):
        return {"results": []}

    monkeypatch.setattr("app.modules.agent.tools.web_search._request_tavily", fake_request)
    result = asyncio.run(search_web("很冷门的检索词"))
    assert result["ok"] is True
    assert result["result_count"] == 0
    assert "未检索到" in result["note"]


def test_search_handles_timeout_and_failure(monkeypatch):
    async def timeout_request(payload):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("app.modules.agent.tools.web_search._request_tavily", timeout_request)
    assert "超时" in asyncio.run(search_web("最新消息"))["error"]

    async def broken_request(payload):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.modules.agent.tools.web_search._request_tavily", broken_request)
    result = asyncio.run(search_web("最新消息"))
    assert result["ok"] is False and "暂时不可用" in result["error"]


def test_tool_reads_turn_switch_from_config():
    async def fake_request(payload):
        return {"results": [{"title": "t", "url": "https://example.com/c", "content": "c"}]}

    import app.modules.agent.tools.web_search as module

    original = module._request_tavily
    module._request_tavily = fake_request
    try:
        off = asyncio.run(web_search.ainvoke(
            {"query": "最新消息"}, config={"configurable": {"web_search": False}},
        ))
        on = asyncio.run(web_search.ainvoke(
            {"query": "最新消息"}, config={"configurable": {"web_search": True}},
        ))
    finally:
        module._request_tavily = original

    assert off["ok"] is False
    assert on["ok"] is True and on["result_count"] == 1


def test_web_tool_not_in_default_capabilities():
    """默认能力清单不列联网工具，只有开启那一轮由 graph 追加专门段落。"""
    assert "web_search" not in default_capabilities()
    assert "web_search" in WEB_SEARCH_CAPABILITY
    assert "本轮已开启" in WEB_SEARCH_CAPABILITY
