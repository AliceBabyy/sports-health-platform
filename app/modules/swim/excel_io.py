"""游泳记录 Excel 导入模板与解析校验（2026-11-04 新增，思路参考 training/excel_io.py）。

模板约定（第一行为表头）：
    日期 | 距离(m) | 时长(分钟) | 主泳姿 | 平均心率(bpm) | 总划水次数 | 趟数 | 平均划频(次/分) | 活动卡路里(kcal) | 备注

- 每行代表一条游泳记录；导入的数据一律按「记录」状态保存（status=recorded）。
- 日期、距离必填；时长建议填写（用于配速）；其余列可留空。
- 主泳姿列填中文：自由泳/蛙泳/仰泳/蝶泳/混合（可留空）。
- 行级校验失败只记录该行错误，不阻断其他行。
"""
from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils.datetime import from_excel

from app.core.constants import SWIM_STROKE_LABELS

SHEET_NAME = "游泳记录"
HELP_SHEET = "填写说明"
DATE_HEADER = "日期"

# 模板表头（顺序即列顺序）
HEADERS = [
    "日期", "距离(m)", "时长(分钟)", "主泳姿", "平均心率(bpm)",
    "总划水次数", "趟数", "平均划频(次/分)", "活动卡路里(kcal)", "备注",
]

# 表头文本 → 内部 key
COL_KEYS = {
    "日期": "record_date",
    "距离(m)": "distance_m",
    "时长(分钟)": "duration_min",
    "主泳姿": "main_stroke",
    "平均心率(bpm)": "avg_heart_rate",
    "总划水次数": "total_strokes",
    "趟数": "laps",
    "平均划频(次/分)": "avg_stroke_rate",
    "活动卡路里(kcal)": "calories",
    "备注": "remark",
}

# 中文泳姿 → 内部 key（反向映射）
STROZE_CN_TO_KEY = {v: k for k, v in SWIM_STROKE_LABELS.items()}

DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日")
MAX_IMPORT_ROWS = 5000

# 数值合理范围
RANGES: dict[str, tuple[float, float]] = {
    "distance_m": (1, 100000),
    "duration_min": (0.1, 1440),
    "avg_heart_rate": (1, 300),
    "total_strokes": (0, 100000),
    "laps": (0, 10000),
    "avg_stroke_rate": (0, 200),
    "calories": (0, 10000),
}


def _column_label(key: str) -> str:
    for header, k in COL_KEYS.items():
        if k == key:
            return header
    return key


# ---------- 模板 ----------

def build_template() -> BytesIO:
    """生成可下载导入模板：游泳记录数据 Sheet（仅表头）+ 填写说明。"""
    buf = BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    ws.append(HEADERS)
    ws_help = wb.create_sheet(HELP_SHEET)
    help_lines = [
        "1. 每行代表一条游泳记录；第一行表头请勿修改，请勿新增列。",
        "2. 日期必填（格式 YYYY-MM-DD，例如 2026-11-03）。",
        "3. 距离(m)必填；时长(分钟)建议填写（用于计算配速）。",
        "4. 主泳姿填中文：自由泳 / 蛙泳 / 仰泳 / 蝶泳 / 混合，可留空。",
        "5. 平均心率、总划水次数、趟数、平均划频、活动卡路里、备注均可留空。",
        "6. 数值范围：距离 1~100000m，时长 0.1~1440 分钟，心率 1~300bpm。",
        "7. 导入的数据将直接作为「已完成记录」保存，不会改动已存在的记录。",
        "8. 示例：2026-11-03 / 1500 / 25 / 自由泳 / 135 / 600 / 30 / 24 / 320 / 今天状态不错",
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
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 10), 20)

    wb.save(buf)
    return buf


# ---------- 解析 ----------

def parse_workbook(content: bytes) -> list[dict]:
    """解析导入文件 → [{sheet, row, cells}]，cells 为表头 → 原始单元格值。

    工作表缺失、表头缺失、日期列/距离列未识别时抛 ValueError（结构性错误）。空行跳过。
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
                raise ValueError(f"数据行数超过上限（{MAX_IMPORT_ROWS} 行）")
            row = tuple(row) + (None,) * (header_len - len(row))
            if all(v is None or (isinstance(v, str) and not v.strip()) for v in row):
                continue
            cells = {}
            for idx, key in col_map.items():
                value = row[idx]
                cells[key] = value.strip() if isinstance(value, str) else value
            rows.append({"sheet": SHEET_NAME, "row": row_idx, "cells": cells})
        return rows
    finally:
        wb.close()


def _match_columns(header: tuple) -> dict[int, str]:
    col_map: dict[int, str] = {}
    for idx, cell in enumerate(header):
        name = str(cell).strip() if cell is not None else ""
        if name in COL_KEYS:
            col_map[idx] = COL_KEYS[name]
    if "record_date" not in col_map.values():
        raise ValueError(f"工作表「{SHEET_NAME}」缺少「{DATE_HEADER}」列")
    if "distance_m" not in col_map.values():
        raise ValueError(f"工作表「{SHEET_NAME}」缺少「距离(m)」列")
    return col_map


# ---------- 行级校验 ----------

def validate_rows(parsed: list[dict]) -> tuple[list[dict], list[dict]]:
    """逐行校验 → (有效记录列表, 错误明细 [{sheet, row, column, reason}])。"""
    valid: list[dict] = []
    errors: list[dict] = []
    for item in parsed:
        cells = item["cells"]
        row_errors: list[dict] = []

        record_date: date | None = None
        if "record_date" in cells:
            record_date, reason = _parse_date(cells.get("record_date"))
            if reason:
                row_errors.append(_err(item, DATE_HEADER, reason))

        # 数值列
        values: dict = {}
        for key in ("distance_m", "duration_min", "avg_heart_rate", "total_strokes", "laps", "avg_stroke_rate", "calories"):
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
            if key in ("distance_m", "avg_heart_rate", "total_strokes", "laps"):
                value = int(value)
            values[key] = value

        # 主泳姿（中文 → key）
        main_stroke = None
        raw_stroke = cells.get("main_stroke")
        if raw_stroke is not None and not (isinstance(raw_stroke, str) and not raw_stroke.strip()):
            stroke_text = str(raw_stroke).strip()
            main_stroke = STROZE_CN_TO_KEY.get(stroke_text)
            if main_stroke is None:
                row_errors.append(_err(item, "主泳姿", "泳姿应为：自由泳/蛙泳/仰泳/蝶泳/混合"))

        remark = cells.get("remark")
        if remark is not None:
            remark = str(remark).strip() or None
            if remark and len(remark) > 255:
                row_errors.append(_err(item, "备注", "备注过长（最多 255 字符）"))

        if "distance_m" not in values:
            row_errors.append(_err(item, "距离(m)", "距离不能为空"))

        if row_errors:
            errors.extend(row_errors)
        else:
            valid.append({
                "record_date": record_date,
                "distance_m": values.get("distance_m"),
                "duration_s": int(round(values["duration_min"] * 60)) if "duration_min" in values else None,
                "main_stroke": main_stroke,
                "avg_heart_rate": values.get("avg_heart_rate"),
                "total_strokes": values.get("total_strokes"),
                "laps": values.get("laps"),
                "avg_stroke_rate": values.get("avg_stroke_rate"),
                "calories": values.get("calories"),
                "remark": remark,
            })
    return valid, errors


def _err(item: dict, column: str, reason: str) -> dict:
    return {"sheet": item["sheet"], "row": item["row"], "column": column, "reason": reason}


def _parse_date(value) -> tuple[date | None, str | None]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "日期不能为空"
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
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
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, None
    if isinstance(value, bool):
        return None, "数值格式不正确"
    try:
        return float(value), None
    except (TypeError, ValueError):
        return None, "数值格式不正确"
