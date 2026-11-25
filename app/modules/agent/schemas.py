"""AI Agent schemas：会话创建/重命名、消息发送入参、技能管理入参。"""
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.modules.agent.models import TITLE_MAX_CHARS
from config import settings


class ConversationIn(BaseModel):
    model_name: str | None = Field(default=None, max_length=64)
    persona_id: int | None = Field(default=None, ge=1)


class ConversationRenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX_CHARS)


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=settings.agent_max_input_chars)
    client_msg_id: str = Field(min_length=1, max_length=64)
    model_name: str | None = Field(default=None, max_length=64)
    # 仅当本会话停在 ask_user 等待回答时有效：跳过该问题，按已有信息继续
    skip_ask: bool = False
    # 本轮的联网开关：只对本次生成生效，默认不联网
    web_search: bool = False


class RegenerateIn(BaseModel):
    client_msg_id: str = Field(min_length=1, max_length=64)
    model_name: str | None = Field(default=None, max_length=64)
    web_search: bool = False


class ContinueIn(BaseModel):
    """继续生成：最近一轮被用户中断时，从已输出的片段接着写。"""
    client_msg_id: str = Field(min_length=1, max_length=64)
    model_name: str | None = Field(default=None, max_length=64)
    web_search: bool = False


class SkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=48)
    key: str = Field(min_length=1, max_length=48)
    slash_alias: str | None = Field(default=None, max_length=24)
    description: str = Field(default="", max_length=200)
    category: str = Field(default="custom", max_length=16)
    kind: Literal["prompt"] = "prompt"
    definition: dict[str, Any]


class SkillStatusIn(BaseModel):
    status: Literal["active", "disabled", "archived"]


class SkillTestIn(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)


class SkillValidateIn(BaseModel):
    kind: Literal["prompt"] | None = None
    definition: dict[str, Any] | None = None


class PersonaIn(BaseModel):
    name: str = Field(min_length=1, max_length=48)
    key: str = Field(min_length=1, max_length=48)
    description: str = Field(default="", max_length=200)
    definition: dict[str, Any]


class PersonaStatusIn(BaseModel):
    status: Literal["active", "disabled"]
