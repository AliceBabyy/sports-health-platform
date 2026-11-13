"""LangGraph 图：单 agent 节点，消息由 checkpointer 承载。

图本身无状态、可复用：系统提示词按当天加载、模型按 config 动态选择；
PostgresSaver 负责线程状态的加载、重放与持久化。节点不捕获模型异常，
失败由 service 层捕获并以 SSE error 事件返回，保持消息通道干净。
"""
from datetime import date

from langchain_core.messages import SystemMessage, trim_messages
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph

from app.ai.models.registry import get_model
from app.ai.prompts.loader import load_system_prompt
from config import settings

WEEKDAYS = ("一", "二", "三", "四", "五", "六", "日")


async def agent_node(state: MessagesState, config: RunnableConfig) -> dict:
    model = get_model(config["configurable"].get("model_name"), required="text")
    today = date.today()
    system_text = load_system_prompt(
        "agent_chat.v1",
        today=today.isoformat(),
        weekday=WEEKDAYS[today.weekday()],
    )
    trimmed = trim_messages(
        state["messages"],
        max_tokens=settings.agent_context_token_budget,
        strategy="last",
        # 第三方兼容模型未实现 get_num_tokens_from_messages，用内置近似计数（约 4 字符 ≈ 1 token）
        token_counter="approximate",
        include_system=False,
        start_on="human",
    )
    response = await model.ainvoke([SystemMessage(content=system_text), *trimmed])
    return {"messages": [response]}


def build_graph(checkpointer) -> StateGraph:
    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.add_edge(START, "agent")
    graph.add_edge("agent", END)
    return graph.compile(checkpointer=checkpointer)
