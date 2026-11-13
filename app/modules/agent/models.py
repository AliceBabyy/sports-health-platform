"""AI Agent 会话表：会话元数据与 LangGraph 线程映射。

消息不建独立表，由 PostgresSaver checkpointer 持久化在框架表（schema langgraph）；
本表只存会话归属、标题、模型与 thread_id（对应 LangGraph 线程）。
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

DEFAULT_TITLE = "新会话"
TITLE_MAX_CHARS = 64
AUTO_TITLE_LEN = 12


class AgentConversation(Base):
    __tablename__ = "agent_conversations"
    __table_args__ = (
        Index("ix_agent_conversations_user_last", "user_id", text("last_message_at DESC")),
        {"comment": "AI Agent 会话（元数据 + LangGraph thread_id；消息由 checkpointer 管理）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        comment="用户 FK，删除账号时级联删除",
    )
    title: Mapped[str] = mapped_column(
        String(TITLE_MAX_CHARS), nullable=False, default=DEFAULT_TITLE, server_default=DEFAULT_TITLE,
        comment="会话标题（首条消息取前 12 字，默认新会话）",
    )
    model_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="会话级模型（可空，用默认模型）",
    )
    thread_id: Mapped[UUID] = mapped_column(
        Uuid, nullable=False, unique=True, comment="LangGraph 线程 ID（checkpointer 键）",
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="最近消息时间（列表排序冗余）",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
        comment="更新时间（ORM onupdate 自动刷新）",
    )
