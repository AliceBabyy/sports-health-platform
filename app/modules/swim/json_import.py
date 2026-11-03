"""游泳记录 JSON 导入校验（2026-11-04 新增，与 Excel 导入语义一致：失败行跳过、不阻断其他行）。

请求格式：
    {"records": [
        {"record_date": "2026-11-03", "distance_m": 1500, "duration_min": 25,
         "main_stroke": "自由泳", "avg_heart_rate": 135, "total_strokes": 600,
         "laps": 30, "avg_stroke_rate": 24, "calories": 320, "remark": "今天状态不错"},
        ...
    ]}
导入一律按记录状态保存。
"""
from datetime import date, datetime

from pydantic import BaseModel, Field, ValidationError

from app.core.constants import SWIM_STROKE_LABELS

STROZE_CN_TO_KEY = {v: k for k, v in SWIM_STROKE_LABELS.items()}


class JsonImportRecordIn(BaseModel):
    record_date: date
    distance_m: int = Field(ge=1)
    duration_min: float | None = Field(default=None, ge=0.1)
    main_stroke: str | None = None
    avg_heart_rate: int | None = Field(default=None, ge=1, le=300)
    total_strokes: int | None = Field(default=None, ge=0)
    laps: int | None = Field(default=None, ge=0)
    avg_stroke_rate: float | None = Field(default=None, ge=0, le=200)
    calories: float | None = Field(default=None, ge=0)
    remark: str | None = Field(default=None, max_length=255)


FIELD_CN = {
    "record_date": "日期",
    "distance_m": "距离(m)",
    "duration_min": "时长(分钟)",
    "main_stroke": "主泳姿",
    "avg_heart_rate": "平均心率(bpm)",
    "total_strokes": "总划水次数",
    "laps": "趟数",
    "avg_stroke_rate": "平均划频(次/分)",
    "calories": "活动卡路里(kcal)",
    "remark": "备注",
}


def validate_json_records(raw_records: list) -> tuple[list[dict], list[dict]]:
    """逐记录校验 → (有效记录列表, 错误明细 [{sheet, row, column, reason}])。"""
    valid: list[dict] = []
    errors: list[dict] = []
    for idx, raw in enumerate(raw_records, start=1):
        if not isinstance(raw, dict):
            errors.append({"sheet": "JSON", "row": idx, "column": "记录", "reason": "记录项必须是对象"})
            continue
        try:
            rec = JsonImportRecordIn(**raw)
        except ValidationError as exc:
            for err in exc.errors():
                loc = err.get("loc") or ()
                column, reason = _map_error(loc, err)
                errors.append({"sheet": "JSON", "row": idx, "column": column, "reason": reason})
            continue

        # 主泳姿中文 → key
        main_stroke = None
        if rec.main_stroke:
            main_stroke = STROZE_CN_TO_KEY.get(rec.main_stroke, rec.main_stroke if rec.main_stroke in STROZE_CN_TO_KEY.values() else None)
            if main_stroke is None:
                errors.append({"sheet": "JSON", "row": idx, "column": "主泳姿",
                               "reason": "泳姿应为：自由泳/蛙泳/仰泳/蝶泳/混合"})
                continue

        valid.append({
            "record_date": rec.record_date,
            "distance_m": rec.distance_m,
            "duration_s": int(round(rec.duration_min * 60)) if rec.duration_min is not None else None,
            "main_stroke": main_stroke,
            "avg_heart_rate": rec.avg_heart_rate,
            "total_strokes": rec.total_strokes,
            "laps": rec.laps,
            "avg_stroke_rate": rec.avg_stroke_rate,
            "calories": rec.calories,
            "remark": rec.remark,
        })
    return valid, errors


def _map_error(loc: tuple, err: dict) -> tuple[str, str]:
    field = loc[0] if loc else ""
    column = FIELD_CN.get(field, field)
    etype = err.get("type", "")
    if etype == "missing":
        return column, "不能为空"
    if "parsing" in etype:
        return column, "日期格式应为 YYYY-MM-DD" if column == "日期" else "格式不正确"
    if etype in ("greater_than", "greater_than_equal", "less_than", "less_than_equal"):
        return column, "超出合理范围"
    if etype in ("string_too_long", "too_long"):
        return column, "过长（超过上限）"
    return column, err.get("msg", "格式不正确")
