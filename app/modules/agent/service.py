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

from langchain_core.messages import HumanMessage
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
    row = get_conversation(db, user_id, conversation_id)
    config = {"configurable": {"thread_id": str(row.thread_id)}}
    state = await runtime["graph"].aget_state(config)
    messages = [
        {"role": "assistant" if m.type == "ai" else "user", "content": m.content}
        for m in state.values.get("messages", [])
    ]
    return {"conversation_id": row.id, "messages": messages}


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


async def stream_reply(db: Session, row: AgentConversation, thread_id: str, runtime: dict, payload):
    config = {"configurable": {"thread_id": thread_id, "model_name": row.model_name}}

    yield _sse("start", {"conversation_id": row.id, "thread_id": thread_id})
    try:
        async for chunk, _meta in runtime["graph"].astream(
            {"messages": [HumanMessage(content=payload.content)]},
            config=config,
            stream_mode="messages",
        ):
            if chunk.content:
                yield _sse("delta", {"content": chunk.content})

        now = datetime.now()
        row.last_message_at = now
        if row.title == DEFAULT_TITLE:
            row.title = payload.content.strip()[:AUTO_TITLE_LEN]
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
