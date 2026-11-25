"""LangGraph 图：工具循环（V2.4 支持按用户技能集装配）。

结构：START → agent ⇄ tools → END。
- agent 节点：bind_tools 后的模型，自主决定是否调用只读工具或技能；
- tools 节点：ToolNode 执行工具/技能，结果作为 ToolMessage 回到 agent；
- 条件边：agent 最后一条消息带 tool_calls 则继续工具循环，否则结束。
- 健康档案测试保存成功后进入 finalize 节点，固定输出结束语并终止，不再回到模型续问。
身份（user_id）由服务端经 config 注入，工具从 config 读取，模型不可填。
"""
import json
from datetime import datetime

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage, convert_to_openai_messages
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
from app.modules.agent.tools.web_search import WEB_SEARCH_TOOL_NAME

MAX_HISTORY_MESSAGES = 20

# 续写模式取值：写入 agent_chat.v8 的 {run_mode}，具体规则由提示词定义，代码只负责传递模式
RUN_MODE_NORMAL = "常规"
RUN_MODE_CONTINUE = "续写"

# 联网工具只在用户打开输入框「联网」开关的那一轮 bind 给模型，同时写进 capabilities；
# 未开启时不列入能力清单，避免模型误以为可以检索外部信息。
WEB_SEARCH_CAPABILITY = (
    "## 联网搜索（本轮已开启）\n"
    "- web_search：检索外部网页与新闻（Tavily）；只用于平台外的实时信息，"
    "回答需保留来源标题与链接。"
)


def _should_continue(state: MessagesState) -> str:
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    return END


PROBE_SAVE_TOOL = "save_health_profile_probe"
PROBE_SAVE_STATUSES = {"created", "updated", "already_exists"}


def _probe_save_payload(message: ToolMessage) -> dict | None:
    """解析健康档案保存工具的结构化结果；非该工具或结果不可解析时返回 None。"""
    if getattr(message, "name", None) != PROBE_SAVE_TOOL:
        return None
    raw = message.content
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _after_tools(state: MessagesState) -> str:
    """健康档案保存成功后直接收口，避免模型在同一个会话里自动开始下一套问题。"""
    payload = _probe_save_payload(state["messages"][-1])
    if payload and payload.get("ok") and payload.get("status") in PROBE_SAVE_STATUSES:
        return "finalize_probe_save"
    return "agent"


def _finalize_probe_save(state: MessagesState) -> dict:
    """固定输出本轮结果并结束，不再给模型继续提问的机会。"""
    payload = _probe_save_payload(state["messages"][-1]) or {}
    status = payload.get("status")
    question_count = payload.get("question_count")
    answered_count = payload.get("answered_count")
    status_text = {
        "created": "已新增一套定制问答",
        "updated": "已更新本套定制问答",
        "already_exists": "本套问答已是最新，未重复写入",
    }.get(status, "已写入健康档案")
    detail = []
    if question_count is not None:
        detail.append(f"共 {question_count} 题")
    if answered_count is not None:
        detail.append(f"记录 {answered_count} 题答案")
    suffix = f"（{'，'.join(detail)}）" if detail else ""
    return {
        "messages": [AIMessage(
            content=f"{status_text}{suffix}。本轮健康档案测试结束；如需重新出题，请明确说“再来一套”。"
        )]
    }


ACTION_TOOL_NAMES = {tool.name for tool in ACTION_TOOLS}


def default_capabilities(tools=None) -> str:
    """交互工具、只读工具与受控写工具分组；技能由 runtime 另行追加。"""
    tools = tools or ALL_TOOLS
    interaction: list[str] = []
    readonly: list[str] = []
    actions: list[str] = []
    for tool in tools:
        if tool.name.startswith("skill_") or tool.name == WEB_SEARCH_TOOL_NAME:
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
        sections.append("## 写入操作（需用户确认后调用）\n" + "\n".join(actions))
    return "\n\n".join(sections)


def make_agent_node(tools, capabilities: str):
    async def agent_node(state: MessagesState, config) -> dict:
        configurable = config["configurable"]
        model_name = configurable.get("model_name")
        web_on = bool(configurable.get("web_search")) and any(
            tool.name == WEB_SEARCH_TOOL_NAME for tool in tools
        )
        bound_tools = tools if web_on else [
            tool for tool in tools if tool.name != WEB_SEARCH_TOOL_NAME
        ]
        model = get_model(model_name, required="tools").bind_tools(bound_tools)

        now = datetime.now()
        persona_block = configurable.get("persona_block") or DEFAULT_PERSONA_BLOCK
        run_mode = configurable.get("run_mode") or RUN_MODE_NORMAL
        cap_text = capabilities
        if web_on:
            cap_text = f"{capabilities}\n\n{WEB_SEARCH_CAPABILITY}"
        system_text = load_system_prompt(
            "agent_chat.v8",
            today=now.date().isoformat(),
            weekday="周" + "一二三四五六日"[now.weekday()],
            now_time=now.strftime("%H:%M"),
            capabilities=cap_text,
            persona_block=persona_block,
            run_mode=run_mode,
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
    graph.add_node("finalize_probe_save", _finalize_probe_save)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _should_continue,
        {"tools": "tools", END: END},
    )
    graph.add_conditional_edges(
        "tools",
        _after_tools,
        {"agent": "agent", "finalize_probe_save": "finalize_probe_save"},
    )
    graph.add_edge("finalize_probe_save", END)
    return graph.compile(checkpointer=checkpointer)
