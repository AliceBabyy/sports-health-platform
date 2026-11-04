"""舞蹈记录 JSON 导入校验（2026-11-04 新增，与 Excel 导入语义一致：失败行跳过、不阻断其他行）。

请求格式：
    {"records": [
        {"record_date": "2026-11-04",
         "start_time": "2026-11-04T19:00:00", "end_time": "2026-11-04T20:30:00",
         "dance_type": "爵士", "stars": 5, "teacher": "王老师",
         "style": "编舞·力量", "duration_min": 90,
         "avg_heart_rate": 130, "max_heart_rate": 160, "calories": 350,
         "remark": "重点练爆发力"},
        ...
    ]}
"""
from pydantic import ValidationError

from app.modules.dance.schemas import DanceRecordIn

# 字段内部名 → 错误明细用中文列名（与 Excel 模板表头一致）
FIELD_CN = {
    "record_date": "日期",
    "start_time": "开始时间",
    "end_time": "结束时间",
    "dance_type": "舞种",
    "stars": "星级",
    "teacher": "舞蹈老师",
    "style": "舞蹈风格",
    "duration_s": "运动时长",
    "avg_heart_rate": "平均心率",
    "max_heart_rate": "最大心率",
    "calories": "总卡路里",
    "remark": "备注",
}


def validate_json_records(raw_records: list) -> tuple[list[DanceRecordIn], list[dict]]:
    """逐行校验 → (有效记录 [DanceRecordIn], 错误明细 [{sheet, row, column, reason}])。"""
    valid: list[DanceRecordIn] = []
    errors: list[dict] = []
    for idx, raw in enumerate(raw_records, start=1):
        if not isinstance(raw, dict):
            errors.append({"sheet": "JSON", "row": idx, "column": "记录", "reason": "记录项必须是对象"})
            continue
        # JSON 导入默认 status=recorded
        raw.setdefault("status", "recorded")
        try:
            valid.append(DanceRecordIn(**raw))
        except ValidationError as exc:
            for err in exc.errors():
                loc = err.get("loc") or ()
                column, reason = _map_error(loc, err)
                errors.append({"sheet": "JSON", "row": idx, "column": column, "reason": reason})
    return valid, errors


def _map_error(loc: tuple, err: dict) -> tuple[str, str]:
    field = loc[0] if loc else ""
    column = FIELD_CN.get(field, field)
    etype = err.get("type", "")
    if etype == "missing":
        return column, "不能为空"
    if "parsing" in etype or etype in ("date_parsing", "time_parsing", "datetime_parsing", "float_parsing", "int_parsing"):
        if column == "日期":
            return column, "日期格式应为 YYYY-MM-DD"
        if column in ("开始时间", "结束时间"):
            return column, "时间格式应为 ISO datetime（如 2026-11-04T19:00:00）"
        return column, "格式不正确"
    if etype in ("greater_than", "greater_than_equal", "less_than", "less_than_equal"):
        return column, "超出合理范围"
    if etype in ("string_too_long", "too_long"):
        return column, "过长（超过上限）"
    if etype == "string_too_short":
        return column, "不能为空"
    return column, err.get("msg", "格式不正确")
