"""健身训练 Excel 导入模板与解析校验（2026-11-04 新增，思路参考身材数据模块 body/excel_io.py）。

模板约定（第一行为表头）：
    计划日期 | 备注 | 动作名称 | 部位 | 重量 kg | 组数 | 每组个数 | 目标重量 kg

- 每行代表一个训练动作；同一「计划日期」的多行动作自动合并为一个训练计划（动作按文件行序）。
- 导入不会修改/覆盖已存在的计划：同一日期可多次导入，每次都会新建一个计划（一日多计划已支持）。
- 行级校验失败只记录该行错误，不阻断其他行。
"""
from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils.datetime import from_excel

SHEET_NAME = "训练计划"
HELP_SHEET = "填写说明"
DATE_HEADER = "计划日期"

# 模板表头（顺序即列顺序）
HEADERS = ["计划日期", "备注", "动作名称", "部位", "重量 kg", "组数", "每组个数", "目标重量 kg"]

# 表头文本 → 内部 key（用于列匹配与错误明细）
COL_KEYS = {
    "计划日期": "plan_date",
    "备注": "remark",
    "动作名称": "exercise_name",
    "部位": "body_part",
    "重量 kg": "weight_kg",
    "组数": "sets",
    "每组个数": "reps",
    "目标重量 kg": "target_weight_kg",
}

DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日")
MAX_IMPORT_ROWS = 5000  # 单文件动作行上限，防止异常超大文件

# 数值合理范围（与 training/schemas.py 的 PlanItemIn 约束对齐）
RANGES: dict[str, tuple[float, float]] = {
    "weight_kg": (0, 999),
    "sets": (1, 99),
    "target_weight_kg": (0, 999),
}


def _column_label(key: str) -> str:
    """内部 key → 表头文本，用于错误明细。"""
    for header, k in COL_KEYS.items():
        if k == key:
            return header
    return key


# ---------- 模板 ----------

def build_template() -> BytesIO:
    """生成可下载导入模板：训练计划数据 Sheet（仅表头）+ 填写说明。"""
    buf = BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    ws.append(HEADERS)
    ws_help = wb.create_sheet(HELP_SHEET)
    help_lines = [
        "1. 每行代表一个训练动作；第一行表头请勿修改，请勿新增列。",
        "2. 计划日期必填（格式 YYYY-MM-DD，例如 2026-11-03）。",
        "3. 动作名称必填；备注、部位、重量、组数、每组个数、目标重量可留空。",
        "4. 每组个数支持自由文本，例如 10+8+6、40s。",
        "5. 数值范围校验：重量 0~999kg，组数 1~99，目标重量 0~999kg。",
        "6. 同一日期的多行动作会合并为一条训练记录（动作按行序排列）。",
        "7. 导入的数据将直接作为训练记录保存（不经过「完成训练」）；同一日期可多次导入，每次都会新建一条记录。",
        "8. 示例：2026-11-03 / 今天练腿 / 杠铃深蹲 / 腿 / 60 / 4 / 10 / 70",
    ]
    for line in help_lines:
        ws_help.append([line])

    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="E8EEF4")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
    ws.freeze_panes = "A2"
    for col in ws.columns:
        max_len = max((len(str(c.value)) for c in col if c.value is not None), default=6)
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 12), 18)

    wb.save(buf)
    return buf


# ---------- 解析 ----------

def parse_workbook(content: bytes) -> list[dict]:
    """解析导入文件 → [{sheet, row, cells}]，cells 为表头 → 原始单元格值。

    工作表「训练计划」缺失、表头缺失、日期列/动作名称列未识别时抛 ValueError（结构性错误）。
    空行跳过。日期/数值的格式校验在 validate_rows 中逐行进行。
    """
    wb = load_workbook(BytesIO(content), read_only=True, data_only=True)
    try:
        if SHEET_NAME not in wb.sheetnames:
            raise ValueError(f"导入文件缺少工作表「{SHEET_NAME}」")
        ws = wb[SHEET_NAME]
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header = next(rows_iter)
        except StopIteration:
            raise ValueError(f"工作表「{SHEET_NAME}」为空，缺少表头行")
        col_map = _match_columns(header)
        header_len = len(header)
        rows: list[dict] = []
        for row_idx, row in enumerate(rows_iter, start=2):
            if row_idx > MAX_IMPORT_ROWS:
                raise ValueError(f"动作行数超过上限（{MAX_IMPORT_ROWS} 行）")
            # read_only 模式尾随空单元格会被截断，补齐到表头长度再按列取
            row = tuple(row) + (None,) * (header_len - len(row))
            if all(v is None or (isinstance(v, str) and not v.strip()) for v in row):
                continue  # 整行空白跳过
            cells = {}
            for idx, key in col_map.items():
                value = row[idx]
                cells[key] = value.strip() if isinstance(value, str) else value
            rows.append({"sheet": SHEET_NAME, "row": row_idx, "cells": cells})
        return rows
    finally:
        wb.close()


def _match_columns(header: tuple) -> dict[int, str]:
    """表头行 → {列索引: key}；未知列忽略，日期列与动作名称列缺失则报错。"""
    col_map: dict[int, str] = {}
    for idx, cell in enumerate(header):
        name = str(cell).strip() if cell is not None else ""
        if name in COL_KEYS:
            col_map[idx] = COL_KEYS[name]
    if "plan_date" not in col_map.values():
        raise ValueError(f"工作表「{SHEET_NAME}」缺少「{DATE_HEADER}」列")
    if "exercise_name" not in col_map.values():
        raise ValueError(f"工作表「{SHEET_NAME}」缺少「动作名称」列")
    return col_map


# ---------- 行级校验 ----------

def validate_rows(parsed: list[dict]) -> tuple[list[dict], list[dict]]:
    """逐行校验 → (有效行列表, 错误明细 [{sheet, row, column, reason}])。

    校验项：计划日期必填且格式正确；动作名称必填；重量/组数/目标重量数值可解析且在合理范围内。
    """
    valid: list[dict] = []
    errors: list[dict] = []
    for item in parsed:
        cells = item["cells"]
        row_errors: list[dict] = []

        plan_date: date | None = None
        if "plan_date" in cells:
            plan_date, reason = _parse_date(cells.get("plan_date"))
            if reason:
                row_errors.append(_err(item, DATE_HEADER, reason))

        exercise_name = _clean_text(cells.get("exercise_name"))
        if not exercise_name:
            row_errors.append(_err(item, _column_label("exercise_name"), "动作名称不能为空"))
        elif len(exercise_name) > 128:
            row_errors.append(_err(item, _column_label("exercise_name"), "动作名称过长（最多 128 字符）"))

        body_part = _clean_text(cells.get("body_part"))
        if body_part and len(body_part) > 32:
            row_errors.append(_err(item, _column_label("body_part"), "部位过长（最多 32 字符）"))

        remark = _clean_text(cells.get("remark"))
        if remark and len(remark) > 255:
            row_errors.append(_err(item, _column_label("remark"), "备注过长（最多 255 字符）"))

        reps = _clean_text(cells.get("reps"))
        if reps and len(reps) > 32:
            row_errors.append(_err(item, _column_label("reps"), "每组个数过长（最多 32 字符）"))

        values: dict[str, float] = {}
        for key in ("weight_kg", "sets", "target_weight_kg"):
            raw = cells.get(key)
            if raw is None:
                continue
            value, reason = _parse_number(raw)
            if reason:
                row_errors.append(_err(item, _column_label(key), reason))
                continue
            lo, hi = RANGES.get(key, (0, 1_000_000))
            if not (lo <= value <= hi):
                row_errors.append(_err(item, _column_label(key), f"超出合理范围（{lo:g}~{hi:g}）"))
                continue
            if key == "sets":
                value = int(value)
            values[key] = value

        if row_errors:
            errors.extend(row_errors)
        else:
            valid.append(
                {
                    "plan_date": plan_date,
                    "remark": remark or None,
                    "exercise_name": exercise_name,
                    "body_part": body_part or None,
                    "weight_kg": values.get("weight_kg"),
                    "sets": values.get("sets"),
                    "reps": reps or None,
                    "target_weight_kg": values.get("target_weight_kg"),
                }
            )
    return valid, errors


def _err(item: dict, column: str, reason: str) -> dict:
    return {"sheet": item["sheet"], "row": item["row"], "column": column, "reason": reason}


def _clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_date(value) -> tuple[date | None, str | None]:
    """单元格值 → (date, None)；失败返回 (None, 原因)。None/空串按必填缺失处理。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "计划日期不能为空"
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Excel 序列日期号
        try:
            return from_excel(value).date(), None
        except Exception:
            return None, "日期格式应为 YYYY-MM-DD"
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date(), None
        except ValueError:
            continue
    return None, "日期格式应为 YYYY-MM-DD"


def _parse_number(value) -> tuple[float | None, str | None]:
    """单元格值 → (float, None)；None/空串返回 (None, None) 表示留空；格式错误返回 (None, 原因)。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, None
    if isinstance(value, bool):
        return None, "数值格式不正确"
    try:
        return float(value), None
    except (TypeError, ValueError):
        return None, "数值格式不正确"
