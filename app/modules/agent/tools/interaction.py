"""人机交互工具：回答中途向用户提问并暂停，用户作答后在同一条回答里继续。

实现走 LangGraph 原生 `interrupt()`：
- 模型调用 `ask_user` → 工具内 `interrupt(payload)` 挂起，checkpointer 保存执行位置；
- 前端收到 `ask` 事件渲染问答卡片；
- 用户作答后服务端用 `Command(resume=answer)` 从同一 thread 继续，工具返回答案给模型。
停止点由代码强制（工具挂起），不依赖提示词让模型“自觉停住”。
"""
from langchain_core.tools import tool
from langgraph.types import interrupt

ASK_TOOL_NAME = "ask_user"
MAX_QUESTION_CHARS = 200
MAX_OPTIONS = 4
MAX_OPTION_CHARS = 40
DEFAULT_QUESTION = "请补充需要的信息后继续"


def _clean_options(options) -> list[str]:
    items: list[str] = []
    for option in options or []:
        text = str(option).strip()
        if text:
            items.append(text[:MAX_OPTION_CHARS])
        if len(items) >= MAX_OPTIONS:
            break
    return items


@tool
async def ask_user(
    question: str,
    options: list[str] | None = None,
    multiple: bool = False,
) -> dict:
    """在回答中途向用户提一个问题并暂停，等用户作答后自动继续本轮任务。

    只在「必须由用户先做决定或提供信息、否则无法继续」时调用：一次只问一个问题，
    问句具体、能用一条消息答完；能给出明确选项时提供 2~4 个短选项，可多选时设
    multiple=true。角色要求逐个收集信息时，应按角色流程逐题调用，不要合并问题。
    调用后立即停止输出，不要继续写正文、不要同时调用其他工具、不要先替用户假设答案。

    用户可以选择跳过：此时返回 `skipped=true`、`answer=null`，表示用户不愿回答，
    应按已有信息继续完成原任务，在回答里说明因此缺少哪部分依据，不要重复提问。
    """
    text = (question or "").strip()[:MAX_QUESTION_CHARS] or DEFAULT_QUESTION
    cleaned = _clean_options(options)
    payload = {
        "question": text,
        "options": cleaned,
        "multiple": bool(multiple and len(cleaned) > 1),
    }
    value = interrupt(payload)
    if isinstance(value, dict):
        answer = str(value.get("answer") or "").strip()
        skipped = bool(value.get("skipped"))
    else:
        answer, skipped = str(value or "").strip(), False
    return {
        "question": text,
        "answer": None if skipped else (answer or None),
        "skipped": skipped,
    }
