"""AI 会话历史结构（turns / blocks / tool_runs）单元测试。

只测纯函数 build_turns，不启动服务、不连数据库。
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.modules.agent.service import build_turns


def _call(name, call_id, **args):
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def test_text_blocks_keep_intermediate_ai_text():
    messages = [
        HumanMessage(content="我上周练了几次"),
        AIMessage(
            content="我先查一下运动记录。",
            tool_calls=[_call("get_workout_summary", "call_1", start="2026-11-10", end="2026-11-16")],
        ),
        ToolMessage(content='{"total": {"records": 3}}', tool_call_id="call_1", name="get_workout_summary"),
        AIMessage(content="上周一共练了 3 次。"),
    ]
    turns = build_turns(messages, [])

    assert len(turns) == 1
    turn = turns[0]
    assert turn["user"] == "我上周练了几次"
    assert [b["content"] for b in turn["blocks"]] == ["我先查一下运动记录。", "上周一共练了 3 次。"]
    run = turn["tool_runs"][0]
    assert set(run) == {"tool", "label", "kind", "args", "data", "call_id"}
    assert run["tool"] == "get_workout_summary"
    assert run["label"] == "运动汇总"
    assert run["kind"] == "base"
    assert run["call_id"] == "call_1"
    assert run["data"] == {"total": {"records": 3}}


def test_tool_results_pair_by_call_id_when_order_differs():
    messages = [
        HumanMessage(content="今天状态怎么样"),
        AIMessage(content="", tool_calls=[
            _call("get_state_records", "call_a", start="2026-11-18", end="2026-11-18"),
            _call("get_profile_info", "call_b"),
        ]),
        ToolMessage(content='{"items": [1]}', tool_call_id="call_a", name="get_state_records"),
        ToolMessage(content='{"name": "lrx"}', tool_call_id="call_b", name="get_profile_info"),
        AIMessage(content="状态还行。"),
    ]
    turns = build_turns(messages, [])

    runs = {r["call_id"]: r for r in turns[0]["tool_runs"]}
    assert runs["call_a"]["data"] == {"items": [1]}
    assert runs["call_b"]["data"] == {"name": "lrx"}
    # 没有正文的中转消息不产生空 block
    assert [b["content"] for b in turns[0]["blocks"]] == ["状态还行。"]


def test_orphan_tool_result_is_kept():
    messages = [
        HumanMessage(content="查一下"),
        AIMessage(content="", tool_calls=[_call("get_swim_records", "call_x")]),
        ToolMessage(content='{"count": 1}', tool_call_id="call_x", name="get_swim_records"),
        ToolMessage(content="not json", tool_call_id="call_y", name="get_swim_records"),
    ]
    turns = build_turns(messages, [])

    runs = turns[0]["tool_runs"]
    assert len(runs) == 2
    assert [r["data"] for r in runs] == [{"count": 1}, {"text": "not json"}]
    assert runs[1]["call_id"] == "call_y"
    assert runs[1]["label"] == "游泳记录"


def test_unmatched_call_id_falls_back_to_first_pending_run():
    # 早期数据可能缺 call_id 或 id 对不上，按顺序兜底，不能丢工具结果
    messages = [
        HumanMessage(content="查一下"),
        AIMessage(content="", tool_calls=[_call("get_swim_records", "call_x")]),
        ToolMessage(content='{"count": 2}', tool_call_id="call_z", name="get_swim_records"),
    ]
    turns = build_turns(messages, [])

    runs = turns[0]["tool_runs"]
    assert len(runs) == 1
    assert runs[0]["data"] == {"count": 2}


def test_legacy_duplicate_human_message_is_merged():
    messages = [
        HumanMessage(content="今天练了什么"),
        AIMessage(content="", tool_calls=[_call("get_fitness_records", "call_1")]),
        HumanMessage(content="今天练了什么"),
        ToolMessage(content='{"count": 1}', tool_call_id="call_1", name="get_fitness_records"),
        AIMessage(content="练了深蹲。"),
    ]
    turns = build_turns(messages, [])

    assert len(turns) == 1
    assert turns[0]["blocks"] == [{"type": "text", "content": "练了深蹲。"}]
    assert len(turns[0]["tool_runs"]) == 1


def test_leading_ai_without_human_is_skipped():
    messages = [
        AIMessage(content="孤立回答"),
        HumanMessage(content="你好"),
        AIMessage(content="你好，有什么可以帮你？"),
    ]
    turns = build_turns(messages, [])

    assert len(turns) == 1
    assert turns[0]["user"] == "你好"
    assert [b["content"] for b in turns[0]["blocks"]] == ["你好，有什么可以帮你？"]


def test_is_generating_follows_run_handle():
    """GET messages 的 generating 只看进程内运行句柄：结束信号置位即视为结束。"""
    import threading

    from app.modules.agent import service

    thread_id = "thread-generating-test"
    service._runs.pop(thread_id, None)
    assert service._is_generating(thread_id) is False

    run = {"done": threading.Event()}
    service._runs[thread_id] = run
    assert service._is_generating(thread_id) is True

    run["done"].set()
    assert service._is_generating(thread_id) is False
    service._runs.pop(thread_id, None)
