"""中断与续写：尾部回滚、中断标记、停止收口与续写前置（假图实现，不启动服务）。"""
import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage

from app.core.exceptions import AppError
from app.modules.agent import service
from app.modules.agent.schemas import ContinueIn
from app.modules.agent.service import (
    _close_interrupted_turn,
    _is_settled_answer,
    _unfinished_tail,
    build_turns,
)


@pytest.fixture(autouse=True)
def _reset_agent_runtime():
    service._running.clear()
    service._client_msgs.clear()
    service._runs.clear()
    yield
    service._running.clear()
    service._client_msgs.clear()
    service._runs.clear()


def _call(name, call_id):
    return {"name": name, "args": {}, "id": call_id, "type": "tool_call"}


def _row(thread_id="thread-x"):
    return SimpleNamespace(
        id=7, user_id=1, thread_id=thread_id, persona_id=None,
        persona_version_no=None, model_name=None, title="新会话", last_message_at=None,
    )


class _GraphState:
    def __init__(self, messages, interrupts=()):
        self.values = {"messages": messages}
        self.interrupts = interrupts


class _FakeGraph:
    """只实现中断收口用到的方法：读状态、把 RemoveMessage/新消息写回状态。"""

    def __init__(self, messages, interrupts=()):
        self.messages = list(messages)
        self.interrupts = interrupts
        self.updates = []

    async def aget_state(self, config):
        return _GraphState(self.messages, self.interrupts)

    async def aupdate_state(self, config, values, as_node=None):
        self.updates.append(values)
        removed = {m.id for m in values.get("messages", []) if isinstance(m, RemoveMessage)}
        for message in values.get("messages", []):
            if not isinstance(message, RemoveMessage):
                self.messages.append(message)
        if removed:
            self.messages = [m for m in self.messages if getattr(m, "id", None) not in removed]


def _patch(monkeypatch, row, graph, personas=None):
    monkeypatch.setattr(service, "get_conversation", lambda db, uid, cid: row)
    monkeypatch.setattr(service, "resolve_for_conversation", lambda db, conv, uid: None)
    monkeypatch.setattr(service, "graph_for_user", lambda db, uid, runtime, persona: graph)
    return {"system_graph": graph, "graphs": {}}


# ---------- 尾部回滚 ----------

def test_unfinished_tail_drops_dangling_tool_call():
    messages = [
        HumanMessage(content="今天练了什么", id="h1"),
        AIMessage(content="", tool_calls=[_call("get_fitness_records", "c1")], id="a1"),
    ]
    assert [m.id for m in _unfinished_tail(messages)] == ["a1"]


def test_unfinished_tail_keeps_completed_tool_trace():
    messages = [
        HumanMessage(content="今天练了什么", id="h1"),
        AIMessage(content="", tool_calls=[_call("get_fitness_records", "c1")], id="a1"),
        ToolMessage(content='{"count": 1}', tool_call_id="c1", name="get_fitness_records", id="t1"),
    ]
    assert _unfinished_tail(messages) == []


def test_unfinished_tail_without_human_is_empty():
    assert _unfinished_tail([AIMessage(content="孤立回答", id="a1")]) == []


# ---------- 停止收口 ----------

def test_is_settled_answer():
    assert _is_settled_answer(AIMessage(content="完整回答")) is True
    assert _is_settled_answer(AIMessage(content="半截", additional_kwargs={"interrupted": True})) is False
    assert _is_settled_answer(AIMessage(content="", tool_calls=[_call("get_profile_info", "c1")])) is False
    assert _is_settled_answer(HumanMessage(content="提问")) is False


def test_close_interrupted_turn_keeps_partial_and_rolls_back_dangling():
    graph = _FakeGraph([
        HumanMessage(content="给我一周计划", id="h1"),
        AIMessage(content="", tool_calls=[_call("get_profile_info", "c1")], id="a1"),
        ToolMessage(content="{}", tool_call_id="c1", name="get_profile_info", id="t1"),
        AIMessage(content="", tool_calls=[_call("save_today_workout_plan", "c2")], id="a2"),
    ])
    assert asyncio.run(_close_interrupted_turn(graph, {}, "先给结论：")) is True

    # 已完成的工具轨迹保留，断在半途的调用被回滚，半截回答作为 interrupted 消息留下
    assert [m.id for m in graph.messages[:3]] == ["h1", "a1", "t1"]
    assert graph.messages[-1].content == "先给结论："
    assert graph.messages[-1].additional_kwargs["interrupted"] is True


def test_close_interrupted_turn_skips_when_answer_already_completed():
    graph = _FakeGraph([
        HumanMessage(content="提问", id="h1"),
        AIMessage(content="完整回答", id="a1"),
    ])
    assert asyncio.run(_close_interrupted_turn(graph, {}, "完整回答")) is False
    assert graph.updates == []


def test_close_interrupted_turn_rolls_back_without_text():
    graph = _FakeGraph([
        HumanMessage(content="提问", id="h1"),
        AIMessage(content="", tool_calls=[_call("get_swim_records", "c1")], id="a1"),
    ])
    assert asyncio.run(_close_interrupted_turn(graph, {}, "")) is True
    assert [m.id for m in graph.messages] == ["h1"]


def test_stop_reply_without_running_run_is_noop(monkeypatch, db):
    row = _row()
    monkeypatch.setattr(service, "get_conversation", lambda db, uid, cid: row)
    result = asyncio.run(service.stop_reply(db, 1, 7, {"system_graph": None}))
    assert result["stopped"] is False
    assert result["closed"] is False


def test_stop_reply_closes_interrupted_turn(monkeypatch, db):
    row = _row()
    graph = _FakeGraph([
        HumanMessage(content="给我一周计划", id="h1"),
        AIMessage(content="", tool_calls=[_call("get_profile_info", "c1")], id="a1"),
    ])
    runtime = _patch(monkeypatch, row, graph)
    done = asyncio.Event()
    done.set()
    service._runs["thread-x"] = {
        "conversation_id": 7, "user_id": 1, "user": "给我一周计划", "partial": "先给结论：",
        "stop": asyncio.Event(), "done": done, "started_at": 0,
    }

    result = asyncio.run(service.stop_reply(db, 1, 7, runtime))
    assert result["stopped"] is True
    assert result["closed"] is True
    assert row.title == "给我一周计划"


# ---------- 续写前置 ----------

def test_prepare_continue_rejects_when_answer_completed(monkeypatch, db):
    row = _row()
    graph = _FakeGraph([
        HumanMessage(content="提问", id="h1"),
        AIMessage(content="完整回答", id="a1"),
    ])
    runtime = _patch(monkeypatch, row, graph)
    with pytest.raises(AppError) as exc:
        asyncio.run(service.prepare_continue(db, 1, 7, runtime, ContinueIn(client_msg_id="c1")))
    assert exc.value.status == 400
    assert service._running == set()
    assert service._runs == {}


def test_prepare_continue_reserves_slot_for_interrupted_turn(monkeypatch, db):
    row = _row()
    graph = _FakeGraph([
        HumanMessage(content="提问", id="h1"),
        AIMessage(content="半截", additional_kwargs={"interrupted": True}, id="p1"),
    ])
    runtime = _patch(monkeypatch, row, graph)
    conv, thread_id = asyncio.run(
        service.prepare_continue(db, 1, 7, runtime, ContinueIn(client_msg_id="c2"))
    )
    assert thread_id == "thread-x"
    assert "thread-x" in service._running
    assert service._runs["thread-x"]["user"] == ""


def test_prepare_continue_rejects_pending_ask(monkeypatch, db):
    row = _row()
    graph = _FakeGraph(
        [HumanMessage(content="提问", id="h1")],
        interrupts=[SimpleNamespace(value={"question": "练几天？"})],
    )
    runtime = _patch(monkeypatch, row, graph)
    with pytest.raises(AppError) as exc:
        asyncio.run(service.prepare_continue(db, 1, 7, runtime, ContinueIn(client_msg_id="c3")))
    assert exc.value.status == 409


# ---------- 流式被打断 ----------

class _SlowGraph:
    """缓慢逐帧产出的假图，用于验证停止信号能打断等待中的下一帧。"""

    def __init__(self, frames=50, delay=0.02):
        self.frames = frames
        self.delay = delay

    async def astream(self, stream_input, config=None, stream_mode=None):
        from langchain_core.messages import AIMessageChunk

        for index in range(self.frames):
            await asyncio.sleep(self.delay)
            yield "messages", (
                AIMessageChunk(content=f"第{index}段"),
                {"langgraph_node": "agent"},
            )


async def _collect_until_stop(run, graph):
    events = []

    async def consume():
        async for event in service._stream_graph(graph, {"messages": []}, {}, [], run):
            events.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)
    run["stop"].set()
    with pytest.raises(service._Stopped):
        await asyncio.wait_for(task, 0.6)
    return events


def test_stream_graph_stops_on_signal():
    run = {"stop": asyncio.Event(), "partial": ""}
    events = asyncio.run(_collect_until_stop(run, _SlowGraph()))

    # 被打断前已经转发了一部分正文，且没有继续跑完 50 帧
    assert events and events[0].startswith("event: delta")
    assert len(events) < 50
    assert "第0段" in run["partial"]


def test_stream_graph_runs_to_end_without_signal():
    run = {"stop": asyncio.Event(), "partial": ""}

    async def consume():
        return [e async for e in service._stream_graph(_SlowGraph(frames=3), {"messages": []}, {}, [], None)]

    events = asyncio.run(consume())
    assert len(events) == 3
    assert run["partial"] == ""


# ---------- 历史渲染 ----------

def test_build_turns_marks_last_turn_interrupted():
    messages = [
        HumanMessage(content="这周训练量"),
        AIMessage(content="这周一共", additional_kwargs={"interrupted": True}, id="p1"),
    ]
    turns = build_turns(messages, [])
    assert turns[-1]["interrupted"] is True
    assert [b["content"] for b in turns[-1]["blocks"]] == ["这周一共"]


def test_build_turns_merges_continuation_text():
    messages = [
        HumanMessage(content="这周训练量"),
        AIMessage(content="这周一共", additional_kwargs={"interrupted": True}, id="p1"),
        AIMessage(content="练了 4 次。", id="a2"),
    ]
    turns = build_turns(messages, [])
    assert [b["content"] for b in turns[0]["blocks"]] == ["这周一共练了 4 次。"]
    assert "interrupted" not in turns[0]


def test_build_turns_does_not_flag_earlier_turns():
    messages = [
        HumanMessage(content="第一问"),
        AIMessage(content="半截", additional_kwargs={"interrupted": True}, id="p1"),
        HumanMessage(content="第二问"),
        AIMessage(content="完整回答", id="a2"),
    ]
    turns = build_turns(messages, [])
    assert "interrupted" not in turns[0]
    assert "interrupted" not in turns[1]
