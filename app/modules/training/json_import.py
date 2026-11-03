"""健身训练 JSON 导入校验（2026-11-04 新增，与 Excel 导入语义一致：失败计划跳过、不阻断其他计划）。

请求格式（与前端导入弹窗 JSON 面板一致）：
    {"plans": [
        {"plan_date": "2026-11-04", "remark": "练胸",
         "items": [{"exercise_name": "杠铃卧推", "body_part": "胸", "weight_kg": 40,
                    "sets": 3, "reps": "10+8+6", "target_weight_kg": 50}]},
        ...
    ]}
"""
from pydantic import ValidationError

from app.modules.training.schemas import JsonImportPlanIn

# 字段内部名 → 错误明细用中文列名（与 Excel 模板表头一致）
FIELD_CN = {
    "plan_date": "计划日期",
    "remark": "备注",
    "exercise_name": "动作名称",
    "body_part": "部位",
    "weight_kg": "重量 kg",
    "sets": "组数",
    "reps": "每组个数",
    "target_weight_kg": "目标重量 kg",
    "items": "动作列表",
}


def validate_json_plans(raw_plans: list) -> tuple[list[JsonImportPlanIn], list[dict]]:
    """逐计划校验 → (有效计划 [JsonImportPlanIn], 错误明细 [{sheet, row, column, reason}])。

    单个计划校验失败只记录该计划错误（含具体动作位置），不阻断其他计划。
    """
    valid: list[JsonImportPlanIn] = []
    errors: list[dict] = []
    for idx, raw in enumerate(raw_plans, start=1):
        if not isinstance(raw, dict):
            errors.append({"sheet": "JSON", "row": idx, "column": "计划", "reason": "计划项必须是对象"})
            continue
        try:
            valid.append(JsonImportPlanIn(**raw))
        except ValidationError as exc:
            for err in exc.errors():
                loc = err.get("loc") or ()
                column, reason = _map_error(loc, err)
                errors.append({"sheet": "JSON", "row": idx, "column": column, "reason": reason})
    return valid, errors


def _map_error(loc: tuple, err: dict) -> tuple[str, str]:
    """pydantic 校验错误 → (中文列名, 中文原因)。loc 形如 ('items', 1, 'exercise_name')。"""
    if loc and loc[0] == "items":
        # 动作列表：'items' / ('items', i) / ('items', i, field)
        if len(loc) == 1:
            return FIELD_CN["items"], "动作列表至少需要 1 条"
        idx = loc[1] + 1
        field = loc[2] if len(loc) > 2 else ""
        column = FIELD_CN.get(field, field) + f"（第 {idx} 个动作）"
    else:
        field = loc[0] if loc else ""
        column = FIELD_CN.get(field, field)

    etype = err.get("type", "")
    if etype == "missing":
        return column, "不能为空"
    if "parsing" in etype or etype in ("date_parsing", "float_parsing", "int_parsing", "bool_parsing", "string_parsing"):
        return column, "日期格式应为 YYYY-MM-DD" if column == "计划日期" else "格式不正确"
    if etype in ("greater_than", "greater_than_equal", "less_than", "less_than_equal"):
        return column, "超出合理范围"
    if etype in ("string_too_long", "too_long"):
        return column, "过长（超过上限）"
    if etype == "string_too_short":
        return column, "不能为空"
    if etype in ("too_short",):
        return column, "至少需要 1 条"
    return column, err.get("msg", "格式不正确")
