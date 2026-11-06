"""舞蹈记录 Excel 导入模板与解析校验（2026-11-04 新增，参考 training/excel_io.py）。

模板约定（第一行为表头）：
    日期 | 开始时间 | 结束时间 | 舞种 | 星级 | 舞蹈老师 | 舞蹈风格 | 运动时长分钟 | 平均心率 | 最大心率 | 总卡路里 | 备注

- 每行代表一条舞蹈课程记录；导入后 status 直接视为 recorded（记录态）。
- 开始/结束时间格式 HH:MM（如 19:00）；若填了起止时间且未填运动时长，则自动计算时长。
- 行级校验失败只记录该行错误，不阻断其他行。
"""
from datetime import date, datetime, time
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils.datetime import from_excel

SHEET_NAME = "舞蹈记录"
HELP_SHEET = "填写说明"
DATE_HEADER = "日期"

# 模板表头（顺序即列顺序）
HEADERS = [
    "日期", "开始时间", "结束时间", "舞种", "星级", "舞蹈老师",
    "舞蹈风格", "运动时长分钟", "平均心率", "最大心率", "总卡路里", "备注",
]

# 表头文本 → 内部 key
COL_KEYS = {
    "日期": "date",
    "开始时间": "start_tm",
    "结束时间": "end_tm",
    "舞种": "dance_type",
    "星级": "stars",
    "舞蹈老师": "teacher",
    "舞蹈风格": "style",
    "运动时长分钟": "duration_min",
    "平均心率": "avg_heart_rate",
    "最大心率": "max_heart_rate",
    "总卡路里": "calories",
    "备注": "remark",
}

DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日")
TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%H时%M分", "%H:%M ")
MAX_IMPORT_ROWS = 5000

# 数值合理范围
RANGES: dict[str, tuple[float, float]] = {
    "stars": (1, 5),
    "avg_heart_rate": (1, 300),
    "max_heart_rate": (1, 300),
    "duration_min": (0, 600),
}


def _column_label(key: str) -> str:
    for header, k in COL_KEYS.items():
        if k == key:
            return header
    return key


# ---------- 模板 ----------

def build_template() -> BytesIO:
    """生成可下载导入模板：舞蹈记录数据 Sheet（仅表头）+ 填写说明。"""
    buf = BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    ws.append(HEADERS)
    ws_help = wb.create_sheet(HELP_SHEET)
    help_lines = [
        "1. 每行代表一条舞蹈课程记录；第一行表头请勿修改，请勿新增列。",
        "2. 日期必填（格式 YYYY-MM-DD，例如 2026-11-04）。",
        "3. 开始时间/结束时间格式 HH:MM（如 19:00），可留空；若都填了且运动时长留空，将自动计算时长。",
        "4. 舞种必填；星级 1~5（必填）；舞蹈老师、舞蹈风格、备注可留空。",
        "5. 运动时长单位为分钟（可选）；平均心率/最大心率单位 bpm；总卡路里单位 kcal。",
        "6. 数值范围：星级 1~5，心率 1~300，运动时长 0~600 分钟。",
        "7. 导入的数据将直接作为舞蹈记录（已完成）保存；同一日期可多次导入，每次新建一条记录。",
        "8. 示例：2026-11-04 / 19:00 / 20:30 / 爵士 / 5 / 王老师 / 编舞·力量 / 90 / 130 / 160 / 350 / 重点练爆发力",
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
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 12), 22)

    wb.save(buf)
    return buf


# ---------- 解析 ----------

def parse_workbook(content: bytes) -> list[dict]:
    """解析导入文件 → [{sheet, row, cells}]，cells 为表头 → 原始单元格值。"""
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
    if "date" not in col_map.values():
        raise ValueError(f"工作表「{SHEET_NAME}」缺少「{DATE_HEADER}」列")
    if "dance_type" not in col_map.values():
        raise ValueError(f"工作表「{SHEET_NAME}」缺少「舞种」列")
    return col_map


# ---------- 行级校验 ----------

def validate_rows(parsed: list[dict]) -> tuple[list[dict], list[dict]]:
    """逐行校验 → (有效行列表, 错误明细 [{sheet, row, column, reason}])。"""
    valid: list[dict] = []
    errors: list[dict] = []
    for item in parsed:
        cells = item["cells"]
        row_errors: list[dict] = []

        date: date | None = None
        if "date" in cells:
            date, reason = _parse_date(cells.get("date"))
            if reason:
                row_errors.append(_err(item, DATE_HEADER, reason))

        start_tm = _parse_time(cells.get("start_tm"))
        end_tm = _parse_time(cells.get("end_tm"))
        if (cells.get("start_tm") not in (None, "") and start_tm is None) or \
           (cells.get("end_tm") not in (None, "") and end_tm is None):
            row_errors.append(_err(item, "开始/结束时间", "时间格式应为 HH:MM（如 19:00）"))

        dance_type = _clean_text(cells.get("dance_type"))
        if not dance_type:
            row_errors.append(_err(item, "舞种", "舞种不能为空"))
        elif len(dance_type) > 32:
            row_errors.append(_err(item, "舞种", "舞种过长（最多 32 字符）"))

        teacher = _clean_text(cells.get("teacher"))
        if teacher and len(teacher) > 64:
            row_errors.append(_err(item, "舞蹈老师", "姓名过长（最多 64 字符）"))

        style = _clean_text(cells.get("style"))
        if style and len(style) > 64:
            row_errors.append(_err(item, "舞蹈风格", "风格过长（最多 64 字符）"))

        remark = _clean_text(cells.get("remark"))
        if remark and len(remark) > 255:
            row_errors.append(_err(item, "备注", "备注过长（最多 255 字符）"))

        values: dict = {}
        for key in ("stars", "avg_heart_rate", "max_heart_rate", "duration_min", "calories"):
            raw = cells.get(key)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                continue
            value, reason = _parse_number(raw)
            if reason:
                row_errors.append(_err(item, _column_label(key), reason))
                continue
            lo, hi = RANGES.get(key, (0, 1e6))
            if not (lo <= value <= hi):
                row_errors.append(_err(item, _column_label(key), f"超出合理范围（{lo:g}~{hi:g}）"))
                continue
            if key in ("stars", "avg_heart_rate", "max_heart_rate"):
                value = int(value)
            values[key] = value

        # 组装 datetime（日期 + 当天时分）
        start_dt = end_dt = None
        if date and start_tm:
            start_dt = datetime.combine(date, start_tm)
        if date and end_tm:
            end_dt = datetime.combine(date, end_tm)
        if start_dt and end_dt and end_dt <= start_dt:
            row_errors.append(_err(item, "结束时间", "结束时间必须晚于开始时间"))

        # 时长：手动填优先（分钟→秒）；否则由起止时间推导
        duration_s = None
        if "duration_min" in values:
            duration_s = int(round(values["duration_min"] * 60))
        elif start_dt and end_dt:
            duration_s = int((end_dt - start_dt).total_seconds())

        if row_errors:
            errors.extend(row_errors)
        else:
            valid.append({
                "date": date,
                "start_time": start_dt,
                "end_time": end_dt,
                "dance_type": dance_type,
                "stars": values.get("stars"),
                "teacher": teacher or None,
                "style": style or None,
                "remark": remark or None,
                "duration_s": duration_s,
                "avg_heart_rate": values.get("avg_heart_rate"),
                "max_heart_rate": values.get("max_heart_rate"),
                "calories": values.get("calories"),
            })
    return valid, errors


def _err(item: dict, column: str, reason: str) -> dict:
    return {"sheet": item["sheet"], "row": item["row"], "column": column, "reason": reason}


def _clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


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


def _parse_time(value) -> time | None:
    """单元格值 → time；失败返回 None。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return from_excel(value).time()
        except Exception:
            return None
    text = str(value).strip()
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).time()
        except ValueError:
            continue
    return None


def _parse_number(value) -> tuple[float | None, str | None]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, None
    if isinstance(value, bool):
        return None, "数值格式不正确"
    try:
        return float(value), None
    except (TypeError, ValueError):
        return None, "数值格式不正确"
