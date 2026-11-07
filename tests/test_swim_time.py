"""游泳起止时间（2026-11-07）：Excel / JSON 导入解析、时长按起止推导、详情字段输出。"""
from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook, load_workbook

from app.modules.swim import excel_io, json_import, service
from app.modules.swim.schemas import SwimRecordIn

USER = 1


def _workbook(headers: list, rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = excel_io.SHEET_NAME
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_template_has_time_columns():
    ws = load_workbook(excel_io.build_template())[excel_io.SHEET_NAME]
    headers = [c.value for c in ws[1]]
    assert "开始时间" in headers and "结束时间" in headers


def test_excel_parses_times_and_derives_duration():
    content = _workbook(excel_io.HEADERS, [["2026-11-03", "19:00", "19:40", 1500, None, "自由泳"]])
    valid, errors = excel_io.validate_rows(excel_io.parse_workbook(content))
    assert errors == []
    row = valid[0]
    assert row["start_time"] == datetime(2026, 11, 3, 19, 0)
    assert row["end_time"] == datetime(2026, 11, 3, 19, 40)
    assert row["duration_s"] == 2400          # 未填时长 → 按起止推导
    assert row["main_stroke"] == "freestyle"


def test_excel_legacy_headers_without_time_still_import():
    """旧模板（无开始/结束时间列）仍可正常导入。"""
    content = _workbook(
        ["日期", "距离(m)", "时长(分钟)", "主泳姿", "备注"],
        [["2026-11-03", 1500, 40, "自由泳", "旧模板"]],
    )
    valid, errors = excel_io.validate_rows(excel_io.parse_workbook(content))
    assert errors == []
    assert valid[0]["start_time"] is None
    assert valid[0]["duration_s"] == 2400


def test_excel_rejects_reversed_times():
    content = _workbook(excel_io.HEADERS, [["2026-11-03", "20:00", "19:00", 1500, None, "自由泳"]])
    valid, errors = excel_io.validate_rows(excel_io.parse_workbook(content))
    assert valid == []
    assert errors[0]["column"] == "结束时间"


def test_json_accepts_hhmm_and_derives_duration():
    valid, errors = json_import.validate_json_records([
        {"date": "2026-11-03", "start_time": "19:00", "end_time": "19:40", "distance_m": 1500},
    ])
    assert errors == []
    assert valid[0]["start_time"] == datetime(2026, 11, 3, 19, 0)
    assert valid[0]["duration_s"] == 2400


def test_json_reversed_times_rejected():
    valid, errors = json_import.validate_json_records([
        {"date": "2026-11-03", "start_time": "20:00", "end_time": "19:00", "distance_m": 1500},
    ])
    assert valid == []
    assert errors[0]["column"] == "结束时间"


def test_service_derives_duration_from_times(db):
    row = service.create_record(db, USER, SwimRecordIn(
        date=date(2026, 11, 3), status="recorded", distance_m=1500,
        start_time=datetime(2026, 11, 3, 19, 0), end_time=datetime(2026, 11, 3, 19, 40),
    ))
    assert row.duration_s == 2400
    out = service.to_dict(row)
    assert out["start_time"] == "2026-11-03T19:00:00"
    assert out["end_time"] == "2026-11-03T19:40:00"


def test_service_keeps_manual_duration(db):
    row = service.create_record(db, USER, SwimRecordIn(
        date=date(2026, 11, 3), status="recorded", distance_m=1500, duration_s=1800,
        start_time=datetime(2026, 11, 3, 19, 0), end_time=datetime(2026, 11, 3, 19, 40),
    ))
    assert row.duration_s == 1800
