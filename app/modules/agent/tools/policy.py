"""角色级工具与技能可见性（V2.4 多角色）。

分两层：

- 代码基线 ``TOOL_PERSONA_SCOPES``：工具名（含 ``skill_<key>``）→ 允许使用的角色 key。
  未登记的工具默认对所有角色可用；只用于「默认范围」和读取旧会话。
- 角色显式白名单：``AgentPersona.tool_grants`` / ``skill_grants`` 非空时覆盖基线。
  管理员的勾选结果落库后，运行时按白名单装配；空数组表示该角色不使用任何工具/技能。
  未配置（NULL）继续沿用基线，保证历史角色不需要迁移即可保持原行为。

专用工具示例：``save_health_profile_probe`` 只在 ``health_profile_test`` 的默认范围中；
管理员显式把它勾给其他角色后，以显式白名单为准。
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

# 工具名（含 skill_<key>） -> 默认允许使用的角色 key；未登记 = 所有角色可用。
TOOL_PERSONA_SCOPES: dict[str, frozenset[str]] = {
    "save_health_profile_probe": frozenset({"health_profile_test"}),
}

SKILL_TOOL_PREFIX = "skill_"


def scoping_enabled() -> bool:
    return bool(TOOL_PERSONA_SCOPES)


def _persona_value(persona, name: str):
    if isinstance(persona, dict):
        return persona.get(name)
    return getattr(persona, name, None)


def _persona_key(persona) -> str | None:
    if isinstance(persona, str):
        return persona
    return _persona_value(persona, "key")


def _grants(persona, name: str) -> frozenset[str] | None:
    if isinstance(persona, str) or persona is None:
        return None
    raw = _persona_value(persona, name)
    if raw is None:
        return None
    return frozenset(str(item) for item in raw)


def tool_visible(tool_name: str, persona_key: str | None) -> bool:
    """代码基线的默认可见性；显式白名单由 tools_for_persona / available_skills 处理。"""
    scopes = TOOL_PERSONA_SCOPES.get(tool_name)
    if scopes is None:
        return True
    return bool(persona_key) and persona_key in scopes


def _tool_allowed(tool_name: str, persona_key: str | None,
                  tool_grants: frozenset[str] | None,
                  skill_grants: frozenset[str] | None) -> bool:
    if tool_name.startswith(SKILL_TOOL_PREFIX):
        if skill_grants is not None:
            return tool_name[len(SKILL_TOOL_PREFIX):] in skill_grants
        return tool_visible(tool_name, persona_key)
    if tool_grants is not None:
        return tool_name in tool_grants
    return tool_visible(tool_name, persona_key)


def tools_for_persona(tools: Iterable, persona) -> list:
    """按角色默认基线或显式白名单过滤工具。

    persona 既可以是角色 key 字符串（旧调用/测试），也可以是带
    ``key`` / ``tool_grants`` / ``skill_grants`` 的 ResolvedPersona 对象。
    """
    tools = list(tools)
    key = _persona_key(persona)
    tool_grants = _grants(persona, "tool_grants")
    skill_grants = _grants(persona, "skill_grants")
    if tool_grants is None and skill_grants is None and not TOOL_PERSONA_SCOPES:
        return tools
    return [
        tool for tool in tools
        if _tool_allowed(tool.name, key, tool_grants, skill_grants)
    ]


def persona_graph_fingerprint(persona) -> str:
    """角色对图装配的影响指纹；完全沿用默认范围且无专用工具时为空串。

    显式白名单会改变工具集合，必须进入图缓存 key；使用哈希避免长列表撑大 key。
    """
    if persona is None:
        return ""
    key = _persona_key(persona)
    if not key:
        return ""
    tool_grants = _grants(persona, "tool_grants")
    skill_grants = _grants(persona, "skill_grants")
    if tool_grants is not None or skill_grants is not None:
        payload = json.dumps(
            {
                "tools": sorted(tool_grants) if tool_grants is not None else None,
                "skills": sorted(skill_grants) if skill_grants is not None else None,
            },
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{key}:g{digest}"
    granted = sorted(
        name for name, scopes in TOOL_PERSONA_SCOPES.items() if key in scopes
    )
    return f"{key}:{','.join(granted)}" if granted else ""
