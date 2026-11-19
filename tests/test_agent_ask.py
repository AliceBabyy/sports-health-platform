"""中途提问（ask_user / interrupt）单元测试。

覆盖三块：
- 工具在真实 LangGraph 图里能中断并在 `Command(resume)` 后继续；
- `build_turns` 把 ask 段插在正确位置并回填答案，不产生工具行；
- 图状态里有挂起 interrupt 时，最后一条 ask 段标记为 pending。
"""

import asyncio
from types import SimpleNamespace
from typing import TypedDict

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.modules.agent.service import _pending_ask, build_turns
from app.modules.agent.tools.interaction import _clean_options, ask_user


class AskState(TypedDict, total=False):
    answer: str


async def _ask_node(state):
    result = await ask_user.ainvoke({
        "question": "要把这套动作加入今日计划吗？",
        "options": ["加入", "暂不加入"],
    })
    return {"answer": result["answer"]}


def _ask_graph():
    graph = StateGraph(AskState)
    graph.add_node("ask", _ask_node)
    graph.add_edge(START, "ask")
    graph.add_edge("ask", END)
    return graph.compile(checkpointer=InMemorySaver())


def test_ask_user_interrupts_and_resumes():
    async def run():
        graph = _ask_graph()
        cfg = {"configurable": {"thread_id": "ask-roundtrip"}}
        payloads = []
        async for chunk in graph.astream({"answer": ""}, cfg, stream_mode="updates"):
            if "__interrupt__" in chunk:
                payloads.extend(item.value for item in chunk["__interrupt__"])
        assert payloads, "图应该在 ask 节点被中断"
        assert payloads[0]["question"].startswith("要把这套动作")
        assert payloads[0]["options"] == ["加入", "暂不加入"]

        state = await graph.ainvoke(Command(resume="加入"), cfg)
        assert state["answer"] == "加入"

    asyncio.run(run())


def test_ask_user_interrupts_through_toolnode():
    """生产链路是 ToolNode 执行工具，确认 interrupt 能从工具节点正确冒泡。"""
    from langchain_core.messages import ToolMessage as _ToolMessage
    from langgraph.graph.message import MessagesState
    from langgraph.prebuilt import ToolNode

    async def agent_node(state):
        last = state["messages"][-1]
        if isinstance(last, _ToolMessage):
            return {"messages": [AIMessage(content="已按你的回答继续。")]}
        return {"messages": [AIMessage(content="", tool_calls=[_ask_call("要保存吗？", ["保存", "不保存"])])]}

    def route(state):
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    async def run():
        graph = StateGraph(MessagesState)
        graph.add_node("agent", agent_node)
        graph.add_node("tools", ToolNode([ask_user]))
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")
        compiled = graph.compile(checkpointer=InMemorySaver())
        cfg = {"configurable": {"thread_id": "ask-toolnode"}}

        payloads = []
        async for chunk in compiled.astream({"messages": [HumanMessage(content="帮我排计划")]}, cfg, stream_mode="updates"):
            if "__interrupt__" in chunk:
                payloads.extend(item.value for item in chunk["__interrupt__"])
        assert payloads and payloads[0]["question"] == "要保存吗？"

        state = await compiled.ainvoke(Command(resume="保存"), cfg)
        tool_message = next(m for m in state["messages"] if isinstance(m, _ToolMessage))
        assert '"answer": "保存"' in tool_message.content
        assert state["messages"][-1].content == "已按你的回答继续。"

    asyncio.run(run())


def test_ask_user_supports_sequential_questions():
    """同一轮任务里连续 ask_user：答完第一题后，图应能继续并在第二题再次中断。"""
    from langchain_core.messages import ToolMessage as _ToolMessage
    from langgraph.graph.message import MessagesState
    from langgraph.prebuilt import ToolNode

    async def agent_node(state):
        asked = [
            m for m in state["messages"]
            if isinstance(m, _ToolMessage) and m.name == "ask_user"
        ]
        if not asked:
            return {"messages": [AIMessage(content="", tool_calls=[_ask_call("第 1 题：最近体重变化？", [], "call_q1")])]}
        if len(asked) == 1:
            return {"messages": [AIMessage(content="", tool_calls=[_ask_call("第 2 题：睡眠如何？", [], "call_q2")])]}
        return {"messages": [AIMessage(content="已收集完两题。")]}

    def route(state):
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode([ask_user]))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    compiled = graph.compile(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "ask-sequential"}}

    async def run():
        payloads = []
        async for chunk in compiled.astream(
            {"messages": [HumanMessage(content="给我做健康档案测试")]}, cfg, stream_mode="updates"
        ):
            if "__interrupt__" in chunk:
                payloads.extend(item.value for item in chunk["__interrupt__"])
        assert [p["question"] for p in payloads] == ["第 1 题：最近体重变化？"]

        async for chunk in compiled.astream(Command(resume="晚饭变晚"), cfg, stream_mode="updates"):
            if "__interrupt__" in chunk:
                payloads.extend(item.value for item in chunk["__interrupt__"])
        assert payloads[-1]["question"] == "第 2 题：睡眠如何？"

        state = await compiled.ainvoke(Command(resume="经常熬夜"), cfg)
        answers = [
            m.content for m in state["messages"]
            if isinstance(m, _ToolMessage)
        ]
        assert any("晚饭变晚" in content for content in answers)
        assert any("经常熬夜" in content for content in answers)
        assert state["messages"][-1].content == "已收集完两题。"

    asyncio.run(run())


def test_ask_user_skip_returns_skipped_flag():
    """用户跳过时 resume 空答案 + skipped，工具应明确回传跳过状态。"""

    class SkipState(TypedDict, total=False):
        result: dict

    async def node(state):
        return {"result": await ask_user.ainvoke({"question": "要把这套动作加入计划吗？", "options": ["加入", "暂不加入"]})}

    async def run():
        graph = StateGraph(SkipState)
        graph.add_node("ask", node)
        graph.add_edge(START, "ask")
        graph.add_edge("ask", END)
        compiled = graph.compile(checkpointer=InMemorySaver())
        cfg = {"configurable": {"thread_id": "ask-skip"}}
        async for _ in compiled.astream({"result": {}}, cfg, stream_mode="updates"):
            pass
        state = await compiled.ainvoke(Command(resume={"answer": None, "skipped": True}), cfg)
        assert state["result"]["answer"] is None
        assert state["result"]["skipped"] is True

    asyncio.run(run())


def _ask_call(question, options, call_id="call_ask"):
    return {
        "name": "ask_user",
        "args": {"question": question, "options": options},
        "id": call_id,
        "type": "tool_call",
    }


def test_build_turns_interleaves_ask_block():
    messages = [
        HumanMessage(content="帮我排个今天的计划"),
        AIMessage(content="先确认一个关键问题。", tool_calls=[_ask_call("要把这套动作加入今日计划吗？", ["加入", "暂不加入"])]),
        ToolMessage(
            content='{"question": "要把这套动作加入今日计划吗？", "options": ["加入", "暂不加入"], "answer": "加入"}',
            tool_call_id="call_ask",
            name="ask_user",
        ),
        AIMessage(content="已加入今日计划。"),
    ]
    turns = build_turns(messages, [])

    assert len(turns) == 1
    blocks = turns[0]["blocks"]
    assert [b["type"] for b in blocks] == ["text", "ask", "text"]
    assert blocks[1]["question"] == "要把这套动作加入今日计划吗？"
    assert blocks[1]["options"] == ["加入", "暂不加入"]
    assert blocks[1]["answer"] == "加入"
    # 问答走 ask 段，不再占一条工具行
    assert turns[0]["tool_runs"] == []


def test_build_turns_renders_multiple_sequential_asks():
    """同一轮里连续两次 ask_user 应各生成一张 ask 段，并分别回填答案。"""
    messages = [
        HumanMessage(content="给我做健康档案测试"),
        AIMessage(content="", tool_calls=[_ask_call("第 1/2 题：最近体重变化？", [], "call_q1")]),
        ToolMessage(
            content='{"question": "第 1/2 题：最近体重变化？", "answer": "晚饭变晚"}',
            tool_call_id="call_q1", name="ask_user",
        ),
        AIMessage(content="", tool_calls=[_ask_call("第 2/2 题：睡眠如何？", [], "call_q2")]),
        ToolMessage(
            content='{"question": "第 2/2 题：睡眠如何？", "answer": "经常熬夜"}',
            tool_call_id="call_q2", name="ask_user",
        ),
        AIMessage(content="已收集完两题。"),
    ]
    turns = build_turns(messages, [])
    blocks = turns[0]["blocks"]
    assert [b["type"] for b in blocks] == ["ask", "ask", "text"]
    assert [b["answer"] for b in blocks[:2]] == ["晚饭变晚", "经常熬夜"]
    assert turns[0]["tool_runs"] == []


def test_build_turns_marks_skipped_ask():
    """跳过的提问保留 ask 段与问题，answer 为空且 skipped=true。"""
    messages = [
        HumanMessage(content="帮我排个今天的计划"),
        AIMessage(content="", tool_calls=[_ask_call("每周能练几天？", ["3 天", "5 天"])]),
        ToolMessage(
            content='{"question": "每周能练几天？", "answer": null, "skipped": true}',
            tool_call_id="call_ask", name="ask_user",
        ),
        AIMessage(content="先按每周 3 天安排。"),
    ]
    turns = build_turns(messages, [])
    blocks = turns[0]["blocks"]
    assert [b["type"] for b in blocks] == ["ask", "text"]
    assert blocks[0]["answer"] is None
    assert blocks[0]["skipped"] is True
    assert blocks[0]["question"] == "每周能练几天？"


def test_pending_ask_marks_last_unanswered_block():
    messages = [
        HumanMessage(content="帮我排个今天的计划"),
        AIMessage(content="先确认一个关键问题。", tool_calls=[_ask_call("要把这套动作加入今日计划吗？", ["加入", "暂不加入"])]),
    ]
    turns = build_turns(messages, [], pending_ask={"question": "要把这套动作加入今日计划吗？", "options": ["加入", "暂不加入"]})

    blocks = turns[0]["blocks"]
    assert [b["type"] for b in blocks] == ["text", "ask"]
    assert blocks[1]["answer"] is None
    assert blocks[1]["pending"] is True
    assert turns[0]["tool_runs"] == []


def test_pending_ask_reads_interrupt_value():
    state = SimpleNamespace(
        interrupts=(SimpleNamespace(value={"question": "要继续吗？", "options": []}),),
    )
    assert _pending_ask(state) == {"question": "要继续吗？", "options": []}
    assert _pending_ask(SimpleNamespace(interrupts=())) is None


def test_clean_options_caps_count_and_length():
    assert _clean_options([" a ", "", "b", "c", "d", "e"]) == ["a", "b", "c", "d"]
    assert _clean_options(None) == []
