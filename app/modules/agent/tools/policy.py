"""角色级工具与技能可见性。

当前产品口径：所有已注册工具与平台技能都可以在所有角色中自由勾选，不再存在
“专项测试技能只允许 health_profile_test”“custom_fitness_plan 只允许 training_coach”
这类角色硬边界。运行时只按角色显式白名单或默认全量装配：

- 角色 ``tool_grants`` / ``skill_grants`` 为 NULL：使用全部工具/全部平台技能；
- 非空数组：严格按管理员勾选结果装配；空数组：该角色不使用任何工具/技能；
- 未登记在数据库中的工具/技能仍不可用，这属于数据完整性，不是角色限制。

性别、管理员门禁、用户归属等非角色边界不在这里处理，仍由各自执行层校验。
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

PROFILE_TEST_PERSONA = "health_profile_test"

# 兼容旧引用；当前为空集合，表示不再有“仅某角色可用”的工具。
PROFILE_TEST_ONLY_TOOLS: frozenset[str] = frozenset()
# 兼容旧引用；当前为空映射，表示未登记工具默认对所有角色可用。
TOOL_PERSONA_SCOPES: dict[str, frozenset[str]] = {}

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
    """工具是否在默认范围内；角色限制已取消，未登记工具默认全部可用。"""
    return True


def _tool_allowed(tool_name: str, persona_key: str | None,
                  tool_grants: frozenset[str] | None,
                  skill_grants: frozenset[str] | None) -> bool:
    if tool_name.startswith(SKILL_TOOL_PREFIX):
        if skill_grants is not None:
            return tool_name[len(SKILL_TOOL_PREFIX):] in skill_grants
        return True
    if tool_grants is not None:
        return tool_name in tool_grants
    return True


def tools_for_persona(tools: Iterable, persona) -> list:
    """按角色显式白名单过滤工具；NULL 表示全部，空数组表示全部不用。

    persona 既可以是角色 key 字符串（旧调用/测试），也可以是带
    ``key`` / ``tool_grants`` / ``skill_grants`` 的 ResolvedPersona / 通用对话 scope。
    """
    tools = list(tools)
    tool_grants = _grants(persona, "tool_grants")
    skill_grants = _grants(persona, "skill_grants")
    if tool_grants is None and skill_grants is None:
        return tools
    return [
        tool for tool in tools
        if _tool_allowed(tool.name, _persona_key(persona), tool_grants, skill_grants)
    ]


def persona_graph_fingerprint(persona) -> str:
    """角色对图装配的影响指纹；显式白名单才影响工具集合。

    NULL 表示全量工具/技能，与平台默认图一致，返回空串以复用常驻图。
    """
    if persona is None:
        return ""
    key = _persona_key(persona)
    if not key:
        return ""
    tool_grants = _grants(persona, "tool_grants")
    skill_grants = _grants(persona, "skill_grants")
    if tool_grants is None and skill_grants is None:
        return ""
    payload = json.dumps(
        {
            "tools": sorted(tool_grants) if tool_grants is not None else None,
            "skills": sorted(skill_grants) if skill_grants is not None else None,
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{key}:g{digest}"
