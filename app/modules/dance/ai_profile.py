"""舞蹈 AI 导入：输出契约（解码期硬约束）、清洗、校验、落库。"""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.modules.dance import json_import
from app.modules.electronic_trainer.ai_import import ImportProfile
from app.modules.electronic_trainer.ai_normalize import (
    clamp_int,
    clean_str,
    pair_times,
    parse_date,
    to_int,
    to_number,
)


class AiDanceRecordOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str = Field(description="上课日期，YYYY-MM-DD")
    start_time: str | None = Field(default=None, description="开始时刻 HH:MM；只知道一端时留空")
    end_time: str | None = Field(default=None, description="结束时刻 HH:MM；只知道一端时留空")
    dance_type: str | None = Field(default=None, description="舞种，如 爵士")
    stars: int | None = Field(default=None, ge=1, le=5, description="主观评价 1~5 星")
    teacher: str | None = Field(default=None, description="授课老师")
    style: str | None = Field(default=None, description="课程风格，如 编舞·力量")
    duration_s: int | None = Field(default=None, description="课程时长，单位秒")
    avg_heart_rate: int | None = Field(default=None, description="平均心率，bpm")
    max_heart_rate: int | None = Field(default=None, description="最大心率，bpm")
    calories: float | None = Field(default=None, description="消耗热量，kcal")
    remark: str | None = Field(default=None, description="用户对这节课的简短描述")


class AiDanceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[AiDanceRecordOut] = Field(default_factory=list, description="舞蹈记录数组")
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

        dance_type = clean_str(record.get("dance_type"), max_length=32)
        duration_s = to_int(record.get("duration_s"))
        if duration_s is not None and duration_s < 1:
            duration_s = None
        if not dance_type and duration_s is None and start is None:
            warnings.append("有一条记录既没有舞种也没有时长，已跳过")
            continue

        out.append({
            "date": day.isoformat(),
            "start_time": start,
            "end_time": end,
            "dance_type": dance_type,
            "stars": clamp_int(record.get("stars"), 1, 5),
            "teacher": clean_str(record.get("teacher"), max_length=64),
            "style": clean_str(record.get("style"), max_length=64),
            "duration_s": duration_s,
            "avg_heart_rate": to_int(record.get("avg_heart_rate")),
            "max_heart_rate": to_int(record.get("max_heart_rate")),
            "calories": to_number(record.get("calories")),
            "remark": clean_str(record.get("remark"), max_length=255),
        })
    return {"records": out}, warnings


def persist(db, user_id: int, records: list) -> tuple[list[int], dict]:
    return json_import.persist_valid_records(db, user_id, records), {}


PROFILE = ImportProfile(
    sport="dance",
    prompt_id="sport_import_dance.v1",
    key="records",
    schema=AiDanceOut,
    normalize=normalize,
    validate=json_import.validate_json_records,
    persist=persist,
)
