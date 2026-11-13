"""AI Agent API 路由（/api/agent 系列）：会话 CRUD、消息读取、流式 SSE 发送。"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.modules.agent import schemas, service
from app.modules.auth.models import User
from database import get_db

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _runtime(request: Request) -> dict:
    return request.app.state.agent_runtime


@router.get("/conversations")
def list_conversations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"list": service.list_conversations(db, user.id)}


@router.post("/conversations")
def create_conversation(
    payload: schemas.ConversationIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.create_conversation(db, user.id, payload.model_name)


@router.put("/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: int,
    payload: schemas.ConversationRenameIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.rename_conversation(db, user.id, conversation_id, payload.title)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await service.delete_conversation(db, user.id, conversation_id, _runtime(request))
    return {"ok": True}


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await service.get_messages(db, user.id, conversation_id, _runtime(request))


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: int,
    payload: schemas.MessageIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # 前置校验与 slot 预占在响应头发送前完成：400/404/409 由全局处理器返回 JSON。
    row, thread_id = await service.acquire_reply_slot(db, user.id, conversation_id, payload)
    return StreamingResponse(
        service.stream_reply(db, row, thread_id, _runtime(request), payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
