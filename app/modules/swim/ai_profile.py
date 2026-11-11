"""游泳 AI 导入：输出契约（解码期硬约束）、清洗、校验、落库。"""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.electronic_trainer.ai_import import ImportProfile
from app.modules.electronic_trainer.ai_normalize import (
    clean_str,
    pair_times,
    parse_date,
    to_int,
    to_number,
)
from app.modules.swim import json_import, service


class AiSwimRecordOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str = Field(description="游泳日期，YYYY-MM-DD")
    start_time: str | None = Field(default=None, description="开始时刻 HH:MM；只知道一端时留空")
    end_time: str | None = Field(default=None, description="结束时刻 HH:MM；只知道一端时留空")
    distance_m: int | None = Field(default=None, description="游泳距离，单位米")
    duration_min: float | None = Field(default=None, description="游泳时长，单位分钟")
    main_stroke: Literal["自由泳", "蛙泳", "仰泳", "蝶泳", "混合"] | None = Field(
        default=None, description="主泳姿，只能是这五个之一"
    )
    avg_heart_rate: int | None = Field(default=None, description="平均心率，bpm")
    total_strokes: int | None = Field(default=None, description="总划水次数")
    laps: int | None = Field(default=None, description="趟数")
    avg_stroke_rate: float | None = Field(default=None, description="平均划频，次/分")
    calories: float | None = Field(default=None, description="消耗热量，kcal")
    remark: str | None = Field(default=None, description="用户对这次游泳的简短描述")


class AiSwimOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[AiSwimRecordOut] = Field(default_factory=list, description="游泳记录数组")
    warnings: list[str] = Field(default_factory=list, description="需要提醒用户的问题，中文短句")


def normalize(raw: dict, today: date) -> tuple[dict, list[str]]:
    warnings = [text for text in (clean_str(w) for w in (raw.get("warnings") or [])) if text]
    records = raw.get("records")
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        records = []

    out: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        day = parse_date(record.get("date"), today)
        if day is None:
            day = today
            warnings.append("有一条记录没给出有效日期，已按今天处理")
        start, end = pair_times(day, record.get("start_time"), record.get("end_time"))
        if (record.get("start_time") or record.get("end_time")) and start is None:
            warnings.append("有一条记录的起止时间不完整，已不写入时间")

        distance = to_int(record.get("distance_m"))
        if distance is None or distance < 1:
            warnings.append("有一条记录没有距离，已跳过")
            continue

        out.append({
            "date": day.isoformat(),
            "start_time": start,
            "end_time": end,
            "distance_m": distance,
            "duration_min": to_number(record.get("duration_min")),
            "main_stroke": clean_str(record.get("main_stroke")),
            "avg_heart_rate": to_int(record.get("avg_heart_rate")),
            "total_strokes": to_int(record.get("total_strokes")),
            "laps": to_int(record.get("laps")),
            "avg_stroke_rate": to_number(record.get("avg_stroke_rate")),
            "calories": to_number(record.get("calories")),
            "remark": clean_str(record.get("remark"), max_length=255),
        })
    return {"records": out}, warnings


def persist(db, user_id: int, records: list) -> tuple[list[int], dict]:
    return service.bulk_create_records(db, user_id, records), {}


PROFILE = ImportProfile(
    sport="swim",
    prompt_id="sport_import_swim.v1",
    key="records",
    schema=AiSwimOut,
    normalize=normalize,
    validate=json_import.validate_json_records,
    persist=persist,
)
