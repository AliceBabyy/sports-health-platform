"""AI 配置管理接口的入参模型。"""
from typing import Literal

from pydantic import BaseModel, Field


class ProviderIn(BaseModel):
    provider_key: str = Field(min_length=2, max_length=48)
    name: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=3, max_length=255)
    api_key_env: str = Field(default="AI_API_KEY", max_length=64)
    api_key: str | None = Field(default=None, max_length=512, description="明文密钥；留空不改")
    clear_api_key: bool = False
    timeout_seconds: float = Field(default=30, gt=0, le=600)
    max_retries: int = Field(default=1, ge=0, le=5)
    extra_headers: dict = Field(default_factory=dict)
    status: Literal["active", "disabled"] = "active"
    remark: str = Field(default="", max_length=200)


class ModelIn(BaseModel):
    alias: str = Field(min_length=1, max_length=64)
    provider_id: int
    upstream_name: str = Field(min_length=1, max_length=128)
    supports_text: bool = True
    supports_vision: bool = False
    supports_tools: bool = False
    supports_structured_output: bool = True
    structured_method: Literal["json_schema", "function_calling", "json_mode"] = "json_schema"
    timeout_seconds: float | None = Field(default=None, gt=0, le=600)
    extra_body: dict = Field(default_factory=dict)
    params: dict = Field(default_factory=dict)
    selectable_for_chat: bool = True
    status: Literal["active", "disabled"] = "active"
    sort_order: int = 0
    remark: str = Field(default="", max_length=200)


class RouteIn(BaseModel):
    feature_key: str = Field(min_length=1, max_length=64)
    model_alias: str = Field(min_length=1, max_length=64)
    timeout_seconds: float | None = Field(default=None, gt=0, le=600)
    params_override: dict = Field(default_factory=dict)
    enabled: bool = True
    remark: str = Field(default="", max_length=200)


class TestIn(BaseModel):
    model_alias: str | None = Field(default=None, max_length=64)
