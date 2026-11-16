"""AI Agent service：会话 CRUD、归属校验、消息读取、流式回复编排。

- 会话元数据走 agent_conversations（同步 ORM/psycopg2）；消息由 checkpointer 承载，
  通过 graph state 读取，不直接 SQL 框架表。
- 同一会话同时只允许一个生成（进程内 async 锁 + 运行集合），重复 client_msg_id 拒绝。
- 硬删除：checkpointer delete_thread + 删 agent_conversations 行，同一编排。
"""
import asyncio
import json
import logging
from datetime import datetime
from uuid import uuid4

from langchain_core.messages import HumanMessage, RemoveMessage
from sqlalchemy.orm import Session

from app.ai.models.registry import MODELS
from app.core.exceptions import AppError
from app.modules.agent.models import AUTO_TITLE_LEN, DEFAULT_TITLE, AgentConversation

logger = logging.getLogger(__name__)

# 进程内运行态：正在生成的 thread_id；client_msg_id -> thread_id（幂等兜底）
_running: set[str] = set()
_client_msgs: dict[str, str] = {}
_state_lock = asyncio.Lock()


def _validate_model(model_name: str | None) -> None:
    if model_name is not None and model_name not in MODELS:
        raise AppError(400, "不支持该模型")


def conversation_to_dict(row: AgentConversation) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "model_name": row.model_name,
        "thread_id": str(row.thread_id),
        "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
        "created_at": row.created_at.isoformat(),
    }


def list_conversations(db: Session, user_id: int) -> list[dict]:
    rows = (
        db.query(AgentConversation)
        .filter(AgentConversation.user_id == user_id)
        .order_by(
            AgentConversation.last_message_at.desc().nullslast(),
            AgentConversation.id.desc(),
        )
        .all()
    )
    return [conversation_to_dict(r) for r in rows]


def get_conversation(db: Session, user_id: int, conversation_id: int) -> AgentConversation:
    row = (
        db.query(AgentConversation)
        .filter(
            AgentConversation.id == conversation_id,
            AgentConversation.user_id == user_id,
        )
        .first()
    )
    if row is None:
        raise AppError(404, "会话不存在")
    return row


def create_conversation(db: Session, user_id: int, model_name: str | None) -> dict:
    _validate_model(model_name)
    row = AgentConversation(user_id=user_id, thread_id=uuid4(), model_name=model_name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return conversation_to_dict(row)


def rename_conversation(db: Session, user_id: int, conversation_id: int, title: str) -> dict:
    row = get_conversation(db, user_id, conversation_id)
    row.title = title.strip()
    db.commit()
    db.refresh(row)
    return conversation_to_dict(row)


async def delete_conversation(db: Session, user_id: int, conversation_id: int, runtime: dict) -> None:
    row = get_conversation(db, user_id, conversation_id)
    thread_id = str(row.thread_id)
    if thread_id in _running:
        raise AppError(409, "该会话正在生成，暂不能删除")
    await runtime["saver"].adelete_thread(thread_id)
    db.delete(row)
    db.commit()


async def get_messages(db: Session, user_id: int, conversation_id: int, runtime: dict) -> dict:
    """按一轮问答（turn）聚合历史，工具调用轨迹随最终回答一起返回。

    checkpointer 完整存着 HumanMessage、带 tool_calls 的中转 AIMessage、ToolMessage 与
    最终 AIMessage；这里不再扁平过滤，而是把同一轮的工具调用与结果归并到对应 turn，
    供前端重建“工具状态 + 明细折叠”，与当次流式视图保持一致。
    """
    row = get_conversation(db, user_id, conversation_id)
    config = {"configurable": {"thread_id": str(row.thread_id)}}
    state = await runtime["graph"].aget_state(config)

    turns: list[dict] = []
    turn: dict | None = None
    for m in state.values.get("messages", []):
        if m.type == "human":
            # 旧版本遗留：工具调用后会重插一条相同 human（且无对应 ToolMessage）。
            # 当前 turn 尚未产生最终回答且内容相同时合并，避免同一问题被拆成两个 turn。
            if turn is not None and turn["assistant"] is None and turn["user"] == m.content:
                continue
            turn = {"user": m.content, "assistant": None, "tool_runs": []}
            turns.append(turn)
        elif turn is None:
            # 没有以用户消息开头的残缺序列，兜底跳过
            continue
        elif m.type == "ai":
            if getattr(m, "tool_calls", None):
                # 工具调用动作：登记 run，等待 ToolMessage 按 tool_call_id 回填
                for tc in m.tool_calls:
                    turn["tool_runs"].append({
                        "tool": tc["name"],
                        "args": tc.get("args", {}),
                        "data": None,
                        "tool_call_id": tc.get("id"),
                    })
            else:
                turn["assistant"] = m.content
        elif m.type == "tool":
            data = _normalize_tool_content(m.content)
            tcid = getattr(m, "tool_call_id", None)
            target = None
            if tcid is not None:
                target = next(
                    (r for r in turn["tool_runs"]
                     if r["tool_call_id"] == tcid and r["data"] is None),
                    None,
                )
            if target is None:
                # 并行/重放等场景按顺序兜底，取第一个未回填的 run
                target = next((r for r in turn["tool_runs"] if r["data"] is None), None)
            if target is not None:
                target["data"] = data
                if getattr(m, "name", None):
                    target["tool"] = m.name
            else:
                # 找不到对应调用的异常态，仍保留结果，避免工具数据丢失
                turn["tool_runs"].append({
                    "tool": getattr(m, "name", "unknown"),
                    "args": {},
                    "data": data,
                    "tool_call_id": tcid,
                })

    result = []
    for t in turns:
        # 内部匹配字段 tool_call_id 不对外暴露
        runs = [
            {"tool": r["tool"], "args": r["args"], "data": r["data"]}
            for r in t["tool_runs"]
        ]
        if t["user"] is not None or t["assistant"] is not None or runs:
            result.append({"user": t["user"], "assistant": t["assistant"], "tool_runs": runs})
    return {"conversation_id": row.id, "turns": result}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _acquire_slot(thread_id: str, client_msg_id: str) -> None:
    async with _state_lock:
        if client_msg_id in _client_msgs:
            raise AppError(409, "请勿重复发送")
        if thread_id in _running:
            raise AppError(409, "该会话正在生成回复")
        _running.add(thread_id)
        _client_msgs[client_msg_id] = thread_id


async def _release_slot(thread_id: str, client_msg_id: str) -> None:
    async with _state_lock:
        _running.discard(thread_id)
        _client_msgs.pop(client_msg_id, None)


async def acquire_reply_slot(db: Session, user_id: int, conversation_id: int, payload):
    """在响应头发送前完成可同步判定的校验与 slot 预占。

    StreamingResponse 会先发 200 头再迭代生成器，若把 400/404/409 留在生成器里，
    头已发出就无法改状态码，只能断连。故提前到构造 StreamingResponse 之前，
    让全局异常处理器返回正确的 JSON 状态码。
    """
    _validate_model(payload.model_name)
    row = get_conversation(db, user_id, conversation_id)
    thread_id = str(row.thread_id)
    await _acquire_slot(thread_id, payload.client_msg_id)
    if payload.model_name is not None:
        row.model_name = payload.model_name
    return row, thread_id


async def prepare_regenerate(db: Session, user_id: int, conversation_id: int, runtime: dict, payload):
    """回滚最近一轮：移除最后一条用户消息及其后的工具中转/AI 回答，返回待重发的用户原文。

    消息由 checkpointer 承载，这里经 graph.update_state + RemoveMessage 按消息 ID 删除，
    不直接写框架表；随后复用 stream_reply 用同一用户原文重新生成，覆盖上一条回答。
    """
    _validate_model(payload.model_name)
    row = get_conversation(db, user_id, conversation_id)
    thread_id = str(row.thread_id)
    await _acquire_slot(thread_id, payload.client_msg_id)
    config = {"configurable": {"thread_id": thread_id}}
    state = await runtime["graph"].aget_state(config)
    msgs = state.values.get("messages", [])

    human_idx = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].type == "human"), None)
    if human_idx is None:
        await _release_slot(thread_id, payload.client_msg_id)
        raise AppError(400, "暂无可重新生成的回答")
    # 保留最后一条用户消息，仅移除其后的工具中转/上一条 AI 回答；
    # 若把用户消息一并删掉，update_state 后消息为空，条件边会取最后一条而越界。
    removed = msgs[human_idx + 1:]
    has_answer = any(m.type == "ai" and not getattr(m, "tool_calls", None) for m in removed)
    if not has_answer:
        await _release_slot(thread_id, payload.client_msg_id)
        raise AppError(400, "暂无可重新生成的回答")

    try:
        await runtime["graph"].aupdate_state(
            config,
            {"messages": [RemoveMessage(id=m.id) for m in removed if getattr(m, "id", None)]},
        )
        human_content = msgs[human_idx].content
        if payload.model_name is not None:
            row.model_name = payload.model_name
        db.commit()
    except Exception:
        await _release_slot(thread_id, payload.client_msg_id)
        raise
    return row, thread_id, human_content


def _normalize_tool_content(content):
    """工具结果可能是 dict 或 JSON 字符串，统一成可序列化对象。"""
    if isinstance(content, str):
        try:
            return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return {"text": content}
    return content


async def stream_reply(db: Session, row: AgentConversation, thread_id: str, runtime: dict, payload, human_content: str | None = None, replay: bool = False):
    # user_id 服务端注入，工具经 config 读取；recursion_limit 限制工具循环轮数
    config = {
        "configurable": {
            "thread_id": thread_id,
            "model_name": row.model_name,
            "user_id": row.user_id,
        },
        "recursion_limit": 10,
    }
    content = human_content or payload.content
    # 重新生成：状态里已保留待回答的用户消息，空输入续跑即可，不再追加重复的 HumanMessage
    stream_input = {"messages": []} if replay else {"messages": [HumanMessage(content=content)]}

    yield _sse("start", {"conversation_id": row.id, "thread_id": thread_id})
    try:
        async for mode, data in runtime["graph"].astream(
            stream_input,
            config=config,
            stream_mode=["messages", "updates"],
        ):
            if mode == "messages":
                message_chunk, metadata = data
                # 只取 agent 节点的正文 token；tools 节点的消息不混入正文
                if metadata.get("langgraph_node") == "agent" and message_chunk.content:
                    yield _sse("delta", {"content": message_chunk.content})
            elif mode == "updates":
                for node, update in data.items():
                    for msg in update.get("messages", []):
                        if node == "agent" and getattr(msg, "tool_calls", None):
                            for tc in msg.tool_calls:
                                yield _sse("tool_start", {"tool": tc["name"], "args": tc["args"]})
                        elif node == "tools":
                            yield _sse("tool_result", {
                                "tool": getattr(msg, "name", None),
                                "data": _normalize_tool_content(msg.content),
                            })

        now = datetime.now()
        row.last_message_at = now
        if row.title == DEFAULT_TITLE:
            row.title = content.strip()[:AUTO_TITLE_LEN]
        db.commit()
        yield _sse("done", {
            "conversation_id": row.id,
            "title": row.title,
            "last_message_at": now.isoformat(),
        })
    except Exception as exc:
        logger.warning("agent stream failed: conv=%s err=%r", row.id, exc)
        db.rollback()
        yield _sse("error", {"message": "生成失败，请稍后重试"})
    finally:
        await _release_slot(thread_id, payload.client_msg_id)
