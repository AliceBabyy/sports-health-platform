"""Configured OpenAI-compatible models and their declared capabilities."""
from dataclasses import dataclass
from typing import Literal

from langchain_openai import ChatOpenAI

from config import settings

Capability = Literal["text", "vision", "tools", "structured_output"]


@dataclass(frozen=True)
class ModelSpec:
    name: str
    capabilities: frozenset[Capability]


# Vision and tool support are deliberately not claimed before endpoint checks.
MODELS = {
    name: ModelSpec(name, frozenset({"text", "structured_output"}))
    for name in ("deepseek-v4.1-flash", "qwen3.8-flash", "qwen3.8-2.4t-a95b")
}


class ModelConfigurationError(ValueError):
    pass


def get_model(name: str | None = None, *, required: Capability = "text") -> ChatOpenAI:
    selected = name or settings.ai_default_model
    spec = MODELS.get(selected)
    if spec is None:
        raise ModelConfigurationError("不支持该模型")
    if required not in spec.capabilities:
        raise ModelConfigurationError("当前模型尚未验证所需能力")
    if not settings.ai_api_key:
        raise ModelConfigurationError("AI_API_KEY 未配置")
    return ChatOpenAI(
        model=selected,
        api_key=settings.ai_api_key,
        base_url=settings.ai_base_url,
        timeout=settings.ai_timeout_seconds,
        max_retries=settings.ai_max_retries,
    )
