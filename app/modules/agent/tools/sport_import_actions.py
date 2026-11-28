"""Agent 受控写工具：通过会话把已完成的健身/游泳/舞蹈记录导入平台。

边界由代码强制，不依赖提示词：
- user_id 从 RunnableConfig 注入，模型不可填、不可伪造；
- 只写 `recorded`，不接受模型指定 status；计划仍走 `save_today_workout_plan`；
- 入参按运动类型分别约束，但复用各运动模块现有 AI 导入的 normalize / validate /
  persist，不新造第二套落库语义；
- 日期可空，缺省为今天；支持今天/昨天/前天等相对日期与 HH:MM 起止时间；
- 一次调用只处理一种运动，可批量传多条记录；任一条校验失败则整批不落库。
"""
from __future__ import annotations

import logging
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.constants import today_local
from app.core.exceptions import AppError
from app.modules.dance.ai_profile import PROFILE as DANCE_PROFILE
from app.modules.electronic_trainer.ai_import import ImportProfile
from app.modules.swim.ai_profile import PROFILE as SWIM_PROFILE
from app.modules.training.ai_profile import PROFILE as TRAINING_PROFILE
from database import SessionLocal

logger = logging.getLogger(__name__)

SPORT = Literal["training", "swim", "dance"]

SPORT_LABELS = {
    "training": "健身",
    "swim": "游泳",
    "dance": "舞蹈",
}

PROFILES: dict[str, ImportProfile] = {
    "training": TRAINING_PROFILE,
    "swim": SWIM_PROFILE,
    "dance": DANCE_PROFILE,
}

# 字段归属：只保留当前运动的字段，避免模型把别的运动字段混进记录。
_ITEM_FIELDS = {"items"}
_SWIM_FIELDS = {
    "distance_m", "duration_min", "main_stroke",
    "total_strokes", "laps", "avg_stroke_rate",
}
_DANCE_FIELDS = {"dance_type", "stars", "teacher", "style", "duration_s"}
_COMMON_FIELDS = {
    "date", "start_time", "end_time", "remark",
    "avg_heart_rate", "max_heart_rate", "calories",
}


class SportImportItemIn(BaseModel):
    """健身动作明细；与训练模块 PlanItemIn 对齐，保持宽松输入、下游统一校验。"""

    model_config = ConfigDict(extra="forbid")

    exercise_name: str = Field(min_length=1, max_length=128, description="动作名称，如 杠铃卧推")
    body_part: str | None = Field(default=None, max_length=32, description="训练部位，可空")
    weight_kg: float | None = Field(default=None, allow_inf_nan=False, ge=0, le=1000,
                                    description="负重 kg，可空")
    sets: int | None = Field(default=None, ge=1, le=99, description="组数，可空")
    reps: str | None = Field(default=None, max_length=32,
                             description="每组次数，可空，如 8 或 10+8+6")
    target_weight_kg: float | None = Field(default=None, allow_inf_nan=False, ge=0, le=1000,
                                           description="目标重量 kg，可空")


class SportImportRecordIn(BaseModel):
    """一条待导入记录；不同 sport 只填对应字段，公共字段三运动通用。"""

    model_config = ConfigDict(extra="forbid")

    date: str | None = Field(default=None, max_length=32,
                             description="记录日期，YYYY-MM-DD 或 今天/昨天/前天；不传按今天")
    start_time: str | None = Field(default=None, max_length=32,
                                   description="开始时间，HH:MM 或完整 ISO；可空")
    end_time: str | None = Field(default=None, max_length=32,
                                 description="结束时间，HH:MM 或完整 ISO；可空")
    remark: str | None = Field(default=None, max_length=255, description="备注，可空")

    # 健身
    items: list[SportImportItemIn] | None = Field(
        default=None, max_length=30, description="健身动作列表；健身记录至少 1 个动作"
    )

    # 游泳
    distance_m: int | None = Field(default=None, ge=1, description="游泳距离（米）；游泳必填")
    duration_min: float | None = Field(default=None, ge=0.1, allow_inf_nan=False,
                                       description="时长（分钟）；游泳或舞蹈可填，舞蹈会自动换算为秒")
    main_stroke: str | None = Field(default=None, max_length=16,
                                    description="主泳姿：自由泳/蛙泳/仰泳/蝶泳/混合；可空")
    total_strokes: int | None = Field(default=None, ge=0, description="总划水次数，可空")
    laps: int | None = Field(default=None, ge=0, description="趟数，可空")
    avg_stroke_rate: float | None = Field(default=None, ge=0, le=200, allow_inf_nan=False,
                                          description="平均划频（次/分），可空")

    # 舞蹈
    dance_type: str | None = Field(default=None, max_length=32, description="舞种，如 爵士")
    stars: int | None = Field(default=None, ge=1, le=5, description="主观评价 1~5 星，可空")
    teacher: str | None = Field(default=None, max_length=64, description="授课老师，可空")
    style: str | None = Field(default=None, max_length=64, description="课程风格，可空")
    duration_s: int | None = Field(default=None, ge=1,
                                   description="舞蹈时长（秒）；只知道分钟时改用 duration_min")

    # 心率与热量：健身/舞蹈通用；游泳不写最大心率
    avg_heart_rate: int | None = Field(default=None, ge=1, le=300, description="平均心率，可空")
    max_heart_rate: int | None = Field(default=None, ge=1, le=300, description="最大心率，可空")
    calories: float | None = Field(default=None, ge=0, allow_inf_nan=False,
                                   description="消耗热量 kcal，可空")


class SportImportRecordsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sport: SPORT = Field(description="运动类型：training=健身，swim=游泳，dance=舞蹈")
    records: list[SportImportRecordIn] = Field(
        min_length=1, max_length=20, description="待导入记录列表，至少 1 条、最多 20 条"
    )


def _clean_record(sport: str, record: SportImportRecordIn) -> dict:
    """按运动类型裁字段，并统一时长单位；业务校验交给各模块现有 profile。"""
    data = record.model_dump(exclude_none=True)

    if sport == "training":
        for key in _SWIM_FIELDS | _DANCE_FIELDS | {"duration_min", "duration_s"}:
            data.pop(key, None)
    elif sport == "swim":
        if data.get("duration_min") is None and data.get("duration_s") is not None:
            data["duration_min"] = data["duration_s"] / 60
        for key in _ITEM_FIELDS | _DANCE_FIELDS | {"duration_s", "max_heart_rate"}:
            data.pop(key, None)
    else:
        if data.get("duration_s") is None and data.get("duration_min") is not None:
            data["duration_s"] = max(1, round(data["duration_min"] * 60))
        for key in _ITEM_FIELDS | _SWIM_FIELDS:
            data.pop(key, None)

    # 公共字段与当前运动字段之外的键不应存在；这里再收口一次，便于后续扩展时发现漏删。
    allowed = _COMMON_FIELDS | (
        _ITEM_FIELDS if sport == "training"
        else _SWIM_FIELDS if sport == "swim"
        else _DANCE_FIELDS
    )
    if sport == "swim":
        allowed -= {"max_heart_rate"}
    return {key: value for key, value in data.items() if key in allowed}


def _raw_payload(sport: str, records: list[SportImportRecordIn]) -> dict:
    key = PROFILES[sport].key
    return {key: [_clean_record(sport, record) for record in records], "warnings": []}


def _result(sport: str, *, ok: bool, status: str, imported: int,
            created_ids: list[int], warnings: list[str], failed: list[dict],
            summary: str, extra: dict | None = None) -> dict:
    return {
        "ok": ok,
        "status": status,
        "sport": sport,
        "label": SPORT_LABELS[sport],
        "imported": imported,
        "created_ids": created_ids,
        "warnings": warnings,
        "failed": failed,
        "summary": summary,
        **(extra or {}),
    }


def import_records(db: Session, user_id: int, payload: SportImportRecordsIn) -> dict:
    """核心逻辑：normalize → validate → persist；可注入 db 单测。"""
    sport = payload.sport
    label = SPORT_LABELS[sport]
    profile = PROFILES[sport]

    try:
        normalized, warnings = profile.normalize(_raw_payload(sport, payload.records), today_local())
        items = normalized.get(profile.key) or []
        if len(items) > profile.max_items:
            return _result(
                sport, ok=False, status="invalid", imported=0, created_ids=[],
                warnings=warnings, failed=[],
                summary=f"单次最多导入 {profile.max_items} 条，请拆开再试。",
            )
        if not items:
            return _result(
                sport, ok=False, status="empty", imported=0, created_ids=[],
                warnings=warnings, failed=[],
                summary=f"没有识别到可导入的{label}记录，请补充日期、{_required_hint(sport)}等信息。",
            )

        valid, errors = profile.validate(items)
        if errors:
            return _result(
                sport, ok=False, status="invalid", imported=0, created_ids=[],
                warnings=warnings, failed=errors,
                summary=f"识别结果未通过校验，未写入任何{label}记录。",
            )

        created_ids, extra = profile.persist(db, user_id, valid)
        extra = extra or {}
        action_text = ""
        if sport == "training":
            action_text = f"，共 {extra.get('items_imported', 0)} 个动作"
        return _result(
            sport, ok=True, status="imported", imported=len(created_ids),
            created_ids=created_ids, warnings=warnings, failed=[],
            summary=f"已导入 {len(created_ids)} 条{label}记录{action_text}。",
            extra=extra,
        )
    except Exception:
        logger.exception("sport import tool failed: sport=%s user=%s", sport, user_id)
        db.rollback()
        return _result(
            sport, ok=False, status="failed", imported=0, created_ids=[],
            warnings=[], failed=[],
            summary="导入过程中出现异常，未确认是否写入记录；请到运动记录页核对后再重试。",
        )


def _required_hint(sport: str) -> str:
    if sport == "training":
        return "动作名称"
    if sport == "swim":
        return "距离"
    return "舞种、时长或开始时间"


def _user_id(config: RunnableConfig | None) -> int:
    uid = (config or {}).get("configurable", {}).get("user_id")
    if not uid:
        raise AppError(400, "缺少用户身份，无法导入运动记录")
    return int(uid)


async def _import_sport_records(
    sport: SPORT,
    records: list[SportImportRecordIn],
    config: RunnableConfig = None,
) -> dict:
    user_id = _user_id(config)
    payload = SportImportRecordsIn(sport=sport, records=records)
    with SessionLocal() as db:
        return import_records(db, user_id, payload)


import_sport_records = StructuredTool.from_function(
    coroutine=_import_sport_records,
    name="import_sport_records",
    description=(
        "把用户在对话中明确要求导入的、已经完成的健身/游泳/舞蹈记录写入平台（recorded）。"
        "只在用户说“记一下 / 导入 / 保存到运动记录”时调用；只是分享、询问或假设计划时不要调用。"
        "一次只选一种运动，可批量传多条记录；不要传 user_id、status、表名或 SQL。"
        "健身填 items[]（exercise_name 必填，可带 body_part/weight_kg/sets/reps/target_weight_kg）；"
        "游泳填 distance_m（必填），可带 duration_min/main_stroke/total_strokes/laps/avg_stroke_rate；"
        "舞蹈填 dance_type/stars/teacher/style/duration_s；只知道分钟时用 duration_min。"
        "日期可空（默认今天），支持今天/昨天/前天或 YYYY-MM-DD；起止时间用 HH:MM 或完整 ISO。"
        "只使用用户给出的数值，不要编造；关键字段不足时先问用户。"
        "返回 status=imported 才表示写入成功；empty/invalid/failed 时不要声称已保存。"
    ),
    args_schema=SportImportRecordsIn,
)
