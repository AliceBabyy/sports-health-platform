"""LangGraph 图：工具循环（V2.4 支持按用户技能集装配）。

结构：START → agent ⇄ tools → END。
- agent 节点：bind_tools 后的模型，自主决定是否调用只读工具或技能；
- tools 节点：ToolNode 执行工具/技能，结果作为 ToolMessage 回到 agent；
- 条件边：agent 最后一条消息带 tool_calls 则继续工具循环，否则结束。
身份（user_id）由服务端经 config 注入，工具从 config 读取，模型不可填。
"""
from datetime import datetime

from langchain_core.messages import SystemMessage, convert_to_openai_messages
from langchain_core.messages.utils import trim_messages
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode

from app.ai.models.registry import get_model
from app.ai.prompts.loader import load_system_prompt
from app.modules.agent.personas.runtime import DEFAULT_PERSONA_BLOCK
from app.modules.agent.tools import ALL_TOOLS
from app.modules.agent.tools.action_definitions import ACTION_TOOLS
from app.modules.agent.tools.interaction import ASK_TOOL_NAME

MAX_HISTORY_MESSAGES = 20


def _should_continue(state: MessagesState) -> str:
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    return END


ACTION_TOOL_NAMES = {tool.name for tool in ACTION_TOOLS}


def default_capabilities(tools=None) -> str:
    """交互工具、只读工具与受控写工具分组；技能由 runtime 另行追加。"""
    tools = tools or ALL_TOOLS
    interaction: list[str] = []
    readonly: list[str] = []
    actions: list[str] = []
    for tool in tools:
        if tool.name.startswith("skill_"):
            continue
        entry = f"- {tool.name}：{(tool.description or '').splitlines()[0]}"
        if tool.name == ASK_TOOL_NAME:
            interaction.append(entry)
        elif tool.name in ACTION_TOOL_NAMES:
            actions.append(entry)
        else:
            readonly.append(entry)
    sections: list[str] = []
    if interaction:
        sections.append("## 与用户交互（调用后会暂停等待回答）\n" + "\n".join(interaction))
    if readonly:
        sections.append("## 只读数据工具\n" + "\n".join(readonly))
    if actions:
        sections.append("## 计划操作（写入，需用户确认后调用）\n" + "\n".join(actions))
    return "\n\n".join(sections)


def make_agent_node(tools, capabilities: str):
    async def agent_node(state: MessagesState, config) -> dict:
        model_name = config["configurable"].get("model_name")
        model = get_model(model_name, required="tools").bind_tools(tools)

        now = datetime.now()
        configurable = config["configurable"]
        persona_block = configurable.get("persona_block") or DEFAULT_PERSONA_BLOCK
        system_text = load_system_prompt(
            "agent_chat.v7",
            today=now.date().isoformat(),
            weekday="周" + "一二三四五六日"[now.weekday()],
            now_time=now.strftime("%H:%M"),
            capabilities=capabilities,
            persona_block=persona_block,
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
