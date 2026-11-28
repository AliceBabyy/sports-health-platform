"""Agent 受控写工具：健身计划、健康档案与运动记录导入。

与只读工具（definitions.py）严格区分：写操作边界由代码强制，不依赖提示词：
- user_id 从 RunnableConfig 注入，模型不可填、不可伪造；
- 健身计划日期固定为今天、状态固定 planned，模型不能指定日期 / 状态 / user_id；
- 运动记录导入只写 recorded，复用三运动 AI 导入的 normalize / validate / persist；
- 动作明细经 Pydantic 严格校验（extra=forbid），约束与训练模块 PlanItemIn 对齐；
- 健康档案专用工具只授权给“健康档案测试”角色，问题与答案经严格校验后复用档案落库逻辑；
- 今日已有完全相同的 planned 计划时不重复创建，返回 already_exists，防止工具循环重复落库。
"""
from __future__ import annotations

from datetime import date

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.constants import TR_STATUS_PLANNED, today_local
from app.core.exceptions import AppError
from app.modules.training import service as training_service
from app.modules.training.models import TrainingRecord
from database import SessionLocal
from .health_profile_actions import save_health_profile_aspect
from .sport_import_actions import import_sport_records


class PlanItemActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_name: str = Field(min_length=1, max_length=128, description="动作名称")
    body_part: str | None = Field(default=None, max_length=32, description="训练部位，可空")
    weight_kg: float | None = Field(default=None, allow_inf_nan=False, ge=0, le=1000,
                                    description="负重 kg，可空")
    sets: int | None = Field(default=None, ge=1, le=99, description="组数，可空")
    reps: str | None = Field(default=None, max_length=32,
                             description="每组次数，可空（如 8 或 8-10）")
    target_weight_kg: float | None = Field(default=None, allow_inf_nan=False, ge=0, le=1000,
                                           description="目标重量 kg，可空")


class SaveTodayPlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PlanItemActionIn] = Field(min_length=1, max_length=30,
                                          description="本次要加入的健身动作，至少 1 个")
    remark: str | None = Field(default=None, max_length=255, description="计划备注，可空")


def _user_id(config: RunnableConfig | None) -> int:
    uid = (config or {}).get("configurable", {}).get("user_id")
    if not uid:
        raise AppError(400, "缺少用户身份，无法保存计划")
    return uid


def _num(value) -> float | None:
    return round(float(value), 2) if value is not None else None


def _payload_signature(items: list[PlanItemActionIn]) -> tuple:
    return tuple(
        (i.exercise_name, i.body_part, _num(i.weight_kg), i.sets,
         i.reps or None, _num(i.target_weight_kg))
        for i in items
    )


def _record_signature(plan: TrainingRecord) -> tuple:
    return tuple(
        (item.exercise_name, item.body_part, _num(item.weight_kg), item.sets,
         item.reps or None, _num(item.target_weight_kg))
        for item in plan.items
    )


def _find_duplicate(db: Session, user_id: int, today: date,
                    payload: SaveTodayPlanIn) -> TrainingRecord | None:
    target = _payload_signature(payload.items)
    for plan in training_service.get_plans_by_date(db, user_id, today):
        if plan.status != TR_STATUS_PLANNED:
            continue
        if _record_signature(plan) == target:
            return plan
    return None


def save_today_plan(db: Session, user_id: int, payload: SaveTodayPlanIn) -> dict:
    """受控写核心逻辑：防重复 + 复用 create_plan 落今日 planned；可注入 db 以便测试。"""
    today = today_local()
    duplicate = _find_duplicate(db, user_id, today, payload)
    if duplicate is not None:
        return {
            "ok": True,
            "status": "already_exists",
            "plan_id": duplicate.id,
            "date": today.isoformat(),
            "item_count": len(payload.items),
            "summary": "今日已有完全相同的健身计划，未重复添加。",
        }

    plan = training_service.create_plan(
        db, user_id, today, payload.items,
        remark=payload.remark,
        status=TR_STATUS_PLANNED,
    )
    return {
        "ok": True,
        "status": "created",
        "plan_id": plan.id,
        "date": today.isoformat(),
        "item_count": len(payload.items),
        "summary": f"已把 {len(payload.items)} 个动作加入今日健身计划。",
    }


async def _save_today_workout_plan(
    items: list[PlanItemActionIn],
    remark: str | None = None,
    config: RunnableConfig = None,
) -> dict:
    user_id = _user_id(config)
    payload = SaveTodayPlanIn(items=items, remark=remark)
    with SessionLocal() as db:
        return save_today_plan(db, user_id, payload)


save_today_workout_plan = StructuredTool.from_function(
    coroutine=_save_today_workout_plan,
    name="save_today_workout_plan",
    description=(
        "把对话中已经得到用户确认的健身动作，保存为今日（planned）健身计划。"
        "仅在用户明确同意加入今日计划后调用；用户未确认或拒绝时不要调用。"
        "日期固定为今天、状态固定为计划，不需要也不能传入日期、状态或用户 id。"
    ),
    args_schema=SaveTodayPlanIn,
)

ACTION_TOOLS = [save_today_workout_plan, save_health_profile_aspect, import_sport_records]
