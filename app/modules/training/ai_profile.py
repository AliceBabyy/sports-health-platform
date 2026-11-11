"""健身训练 AI 导入：输出契约（解码期硬约束）、清洗、校验、落库。

输出模型只负责“约束形状与枚举”，业务真值约束（重量范围、条数上限等）留给
`json_import.validate_json_plans`，避免模型为了满足 schema 去编造数据。
"""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.modules.electronic_trainer.ai_import import ImportProfile
from app.modules.electronic_trainer.ai_normalize import (
    clean_str,
    pair_times,
    parse_date,
    to_int,
    to_number,
)
from app.modules.training import json_import


class AiTrainingItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_name: str = Field(description="动作名称，如 杠铃卧推")
    body_part: str | None = Field(default=None, description="训练部位，只在用户明确提到时填写")
    weight_kg: float | None = Field(default=None, description="重量，单位 kg")
    sets: int | None = Field(default=None, description="组数")
    reps: str | None = Field(default=None, description="每组次数，保留原始写法，如 10+8+6")
    target_weight_kg: float | None = Field(default=None, description="目标重量，单位 kg，只在用户提到时填写")


class AiTrainingPlanOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str = Field(description="训练日期，YYYY-MM-DD")
    start_time: str | None = Field(default=None, description="开始时刻 HH:MM；只知道一端时留空")
    end_time: str | None = Field(default=None, description="结束时刻 HH:MM；只知道一端时留空")
    remark: str | None = Field(default=None, description="用户对这次训练的简短描述")
    avg_heart_rate: int | None = Field(default=None, description="平均心率，bpm")
    max_heart_rate: int | None = Field(default=None, description="最大心率，bpm")
    calories: float | None = Field(default=None, description="消耗热量，kcal")
    items: list[AiTrainingItemOut] = Field(default_factory=list, description="这次训练做的动作列表")


class AiTrainingOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plans: list[AiTrainingPlanOut] = Field(default_factory=list, description="训练记录数组")
    warnings: list[str] = Field(default_factory=list, description="需要提醒用户的问题，中文短句")


def _clean_reps(value) -> str | None:
    """每组次数保留原始组合写法，只去掉尾部单位（模型常带「次」）。"""
    text = clean_str(value, max_length=32)
    if text is None:
        return None
    return text[:-1] if text.endswith("次") and len(text) > 1 else text


def normalize(raw: dict, today: date) -> tuple[dict, list[str]]:
    warnings = [text for text in (clean_str(w) for w in (raw.get("warnings") or [])) if text]
    plans = raw.get("plans")
    if isinstance(plans, dict):
        plans = [plans]
    if not isinstance(plans, list):
        plans = []

    out: list[dict] = []
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        day = parse_date(plan.get("date"), today)
        if day is None:
            day = today
            warnings.append("有一条记录没给出有效日期，已按今天处理")
        start, end = pair_times(day, plan.get("start_time"), plan.get("end_time"))
        if (plan.get("start_time") or plan.get("end_time")) and start is None:
            warnings.append("有一条记录的起止时间不完整，已不写入时间")

        items: list[dict] = []
        for item in plan.get("items") or []:
            if not isinstance(item, dict):
                continue
            name = clean_str(item.get("exercise_name"), max_length=128)
            if name is None:
                continue
            items.append({
                "exercise_name": name,
                "body_part": clean_str(item.get("body_part"), max_length=32),
                "weight_kg": to_number(item.get("weight_kg")),
                "sets": to_int(item.get("sets")),
                "reps": _clean_reps(item.get("reps")),
                "target_weight_kg": to_number(item.get("target_weight_kg")),
            })
        if not items:
            warnings.append("有一条记录没有可用的动作，已跳过")
            continue

        out.append({
            "date": day.isoformat(),
            "start_time": start,
            "end_time": end,
            "remark": clean_str(plan.get("remark"), max_length=255),
            "avg_heart_rate": to_int(plan.get("avg_heart_rate")),
            "max_heart_rate": to_int(plan.get("max_heart_rate")),
            "calories": to_number(plan.get("calories")),
            "items": items,
        })
    return {"plans": out}, warnings


def persist(db, user_id: int, plans: list) -> tuple[list[int], dict]:
    ids, items_imported = json_import.persist_valid_plans(db, user_id, plans)
    return ids, {"items_imported": items_imported}


PROFILE = ImportProfile(
    sport="training",
    prompt_id="sport_import_training.v1",
    key="plans",
    schema=AiTrainingOut,
    normalize=normalize,
    validate=json_import.validate_json_plans,
    persist=persist,
)
