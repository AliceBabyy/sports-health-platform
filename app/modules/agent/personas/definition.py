"""角色定义校验：只允许 {schema_version, prompt}。

角色是会话级人设，不承载工具、代码、SQL 或数据源声明；工具可见范围由服务端
`tools/policy.py` 统一装配，不写进用户可编辑的定义。
"""
from dataclasses import dataclass
from typing import Any

from config import settings

SCHEMA_VERSION = 1
PERSONA_KEYS = {"schema_version", "prompt"}


class PersonaInvalid(ValueError):
    """角色定义不合法；errors 结构与技能校验保持一致，供接口直接返回。"""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__("角色定义不合法")


@dataclass(frozen=True)
class PersonaDefinition:
    schema_version: int
    prompt: str
    raw: dict


def _err(errors: list[dict], field: str, reason: str) -> None:
    errors.append({"field": field, "reason": reason})


def parse_persona_definition(raw: Any) -> PersonaDefinition:
    errors: list[dict] = []
    if not isinstance(raw, dict):
        raise PersonaInvalid([{"field": "definition", "reason": "定义必须是对象"}])

    extra = set(raw) - PERSONA_KEYS
    if extra:
        _err(errors, "definition", "不允许的字段：" + "、".join(sorted(extra)))
    if raw.get("schema_version") != SCHEMA_VERSION:
        _err(errors, "schema_version", "仅支持 schema_version=1")

    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        _err(errors, "prompt", "角色提示词不能为空")
    elif len(prompt.strip()) > settings.agent_persona_max_chars:
        _err(errors, "prompt", f"角色提示词最多 {settings.agent_persona_max_chars} 字")

    if errors:
        raise PersonaInvalid(errors)
    return PersonaDefinition(SCHEMA_VERSION, prompt.strip(), raw)


def validate_definition(definition: Any) -> tuple[list[dict], list[str]]:
    try:
        parse_persona_definition(definition)
        return [], []
    except PersonaInvalid as exc:
        return exc.errors, []
