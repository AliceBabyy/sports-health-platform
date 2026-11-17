"""LangGraph 图：工具循环（V2.4 支持按用户技能集装配）。

结构：START → agent ⇄ tools → END。
- agent 节点：bind_tools 后的模型，自主决定是否调用只读工具或技能；
- tools 节点：ToolNode 执行工具/技能，结果作为 ToolMessage 回到 agent；
- 条件边：agent 最后一条消息带 tool_calls 则继续工具循环，否则结束。
身份（user_id）由服务端经 config 注入，工具从 config 读取，模型不可填。
"""
from datetime import date

from langchain_core.messages import SystemMessage, convert_to_openai_messages
from langchain_core.messages.utils import trim_messages
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode

from app.ai.models.registry import get_model
from app.ai.prompts.loader import load_system_prompt
from app.modules.agent.tools import ALL_TOOLS
from app.modules.agent.tools.action_definitions import ACTION_TOOLS

MAX_HISTORY_MESSAGES = 20


def _should_continue(state: MessagesState) -> str:
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    return END


ACTION_TOOL_NAMES = {tool.name for tool in ACTION_TOOLS}


def default_capabilities(tools=None) -> str:
    """只读工具与受控写工具分组；技能由 runtime 另行追加。"""
    tools = tools or ALL_TOOLS
    lines = ["## 只读数据工具"]
    action_lines: list[str] = []
    for tool in tools:
        if tool.name.startswith("skill_"):
            continue
        entry = f"- {tool.name}：{(tool.description or '').splitlines()[0]}"
        if tool.name in ACTION_TOOL_NAMES:
            action_lines.append(entry)
        else:
            lines.append(entry)
    if action_lines:
        lines.append("")
        lines.append("## 计划操作（写入，需用户确认后调用）")
        lines.extend(action_lines)
    return "\n".join(lines)


def make_agent_node(tools, capabilities: str):
    async def agent_node(state: MessagesState, config) -> dict:
        model_name = config["configurable"].get("model_name")
        model = get_model(model_name, required="tools").bind_tools(tools)

        today = date.today()
        system_text = load_system_prompt(
            "agent_chat.v4",
            today=today.isoformat(),
            weekday="周" + "一二三四五六日"[today.weekday()],
            capabilities=capabilities,
        )

        trimmed = trim_messages(
            convert_to_openai_messages(state["messages"]),
            max_tokens=MAX_HISTORY_MESSAGES,
            strategy="last",
            token_counter=len,
            start_on="human",
            include_system=True,
        )
        response = await model.ainvoke([SystemMessage(content=system_text), *trimmed])
        return {"messages": [response]}

    return agent_node


def build_graph(checkpointer, tools=None, capabilities: str | None = None):
    tools = tools or ALL_TOOLS
    capabilities = capabilities or default_capabilities(tools)
    graph = StateGraph(MessagesState)
    graph.add_node("agent", make_agent_node(tools, capabilities))
    graph.add_node("tools", ToolNode(tools))

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _should_continue,
        {"tools": "tools", END: END},
    )
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)
