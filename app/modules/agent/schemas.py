"""AI Agent schemas：会话创建/重命名、消息发送入参。"""
from pydantic import BaseModel, Field

from app.modules.agent.models import TITLE_MAX_CHARS
from config import settings


class ConversationIn(BaseModel):
    model_name: str | None = Field(default=None, max_length=64)


class ConversationRenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX_CHARS)


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=settings.agent_max_input_chars)
    client_msg_id: str = Field(min_length=1, max_length=64)
    model_name: str | None = Field(default=None, max_length=64)
