"""Agent 工具目录：管理员勾选角色工具时的稳定清单与展示文案。

只收录实际装配到图里的基础工具、交互工具和受控写工具；技能以 ``skill_<key>``
单独在 skill_grants 中管理，不混进工具白名单。
"""
from __future__ import annotations

from .action_definitions import ACTION_TOOLS
from .definitions import ALL_TOOLS
from .interaction import ASK_TOOL_NAME, ask_user

TOOL_LABELS = {
    "get_workout_summary": "运动汇总",
    "get_fitness_records": "健身记录",
    "get_swim_records": "游泳记录",
    "get_dance_records": "舞蹈记录",
    "get_body_measurements": "身材数据",
    "get_state_records": "状态记录",
    "get_cycle_records": "生理周期",
    "get_profile_info": "个人资料",
    "save_today_workout_plan": "保存今日计划",
    "save_health_profile_probe": "保存健康档案定制问答",
    "ask_user": "向用户提问",
}

TOOL_KINDS = {
    "ask_user": "interaction",
    "save_today_workout_plan": "write",
    "save_health_profile_probe": "write",
}


def _description(tool) -> str:
    return (getattr(tool, "description", "") or "").strip().replace("\n", " ")[:200]


def tool_options() -> list[dict]:
    """返回去重后的工具选项，按只读、交互、写入排序。"""
    order = {"read": 0, "interaction": 1, "write": 2}
    seen = set()
    options = []
    for tool in [*ALL_TOOLS, ask_user, *ACTION_TOOLS]:
        name = tool.name
        if name in seen:
            continue
        seen.add(name)
        kind = TOOL_KINDS.get(name, "read")
        options.append({
            "name": name,
            "label": TOOL_LABELS.get(name, name),
            "kind": kind,
            "description": _description(tool),
        })
    return sorted(options, key=lambda item: (order.get(item["kind"], 99), item["name"]))


def tool_names() -> set[str]:
    return {item["name"] for item in tool_options()}


__all__ = ["TOOL_LABELS", "TOOL_KINDS", "ASK_TOOL_NAME", "tool_options", "tool_names"]
