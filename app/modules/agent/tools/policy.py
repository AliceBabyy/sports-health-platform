"""角色级工具可见性预留（V2.4 多角色）。

当前注册表为空：所有角色与普通会话都装配全量工具（只读工具 + 受控写工具 + 用户技能）。
未来若出现「只在特定角色生效」的专用工具/技能，在 `TOOL_PERSONA_SCOPES` 登记
「工具名 -> 允许的角色 key 集合」即可；未登记的工具仍对所有角色可用。
过滤发生在服务端装配阶段，被排除的工具不会 bind 给模型，不依赖提示词约束。
"""
from __future__ import annotations

from collections.abc import Iterable

# 工具名（含 skill_<key>） -> 允许使用的角色 key；未登记 = 所有角色可用。
TOOL_PERSONA_SCOPES: dict[str, frozenset[str]] = {}


def scoping_enabled() -> bool:
    return bool(TOOL_PERSONA_SCOPES)


def tool_visible(tool_name: str, persona_key: str | None) -> bool:
    scopes = TOOL_PERSONA_SCOPES.get(tool_name)
    if scopes is None:
        return True
    return bool(persona_key) and persona_key in scopes


def tools_for_persona(tools: Iterable, persona_key: str | None) -> list:
    tools = list(tools)
    if not TOOL_PERSONA_SCOPES:
        return tools
    return [tool for tool in tools if tool_visible(tool.name, persona_key)]


def persona_graph_fingerprint(persona) -> str:
    """角色对图装配的影响指纹；当前恒为空串，表示无需按角色另编译图。

    只有「该角色被授予了角色级专用工具」时才返回非空指纹，作为图缓存 key 的一部分。
    """
    if not TOOL_PERSONA_SCOPES:
        return ""
    key = getattr(persona, "key", None)
    if not key:
        return ""
    granted = sorted(
        name for name, scopes in TOOL_PERSONA_SCOPES.items() if key in scopes
    )
    return f"{key}:{','.join(granted)}" if granted else ""
