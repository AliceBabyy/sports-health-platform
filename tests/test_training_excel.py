"""健身训练 Excel 导入单测（2026-11-04 新增：模板生成 / 解析 / 行级校验 / 按日期分组建记录）。

2026-11-04 改版：导入数据 status 直接为 recorded（训练记录，写 end_time），不再经 planned。
2026-11-07 改版：模板新增可选「开始时间 / 结束时间」两列（HH:MM），未填时长时按起止推导。
"""
from datetime import date, datetime
from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from app.core.constants import TR_STATUS_RECORDED
from app.modules.training import excel_io, service
from app.modules.training.schemas import PlanItemIn

USER = 1

HEADERS = excel_io.HEADERS


def _make_workbook(rows: list[list]) -> bytes:
    """按模板表头构造 xlsx 内容（第一行表头，后续为数据行）。"""
    buf = BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = excel_io.SHEET_NAME
    ws.append(HEADERS)
    for r in rows:
        ws.append(r)
    wb.save(buf)
    return buf.getvalue()


def test_template_build_and_parse_back():
    """模板可生成：非空 xlsx，读回表头与模板一致，且含「填写说明」sheet。"""
    buf = excel_io.build_template()
    data = buf.getvalue()
    assert len(data) > 1000
    wb = load_workbook(BytesIO(data), read_only=True)
    try:
        assert wb.sheetnames == [excel_io.SHEET_NAME, excel_io.HELP_SHEET]
        ws = wb[excel_io.SHEET_NAME]
        header = next(ws.iter_rows(values_only=True))
        assert list(header) == HEADERS
    finally:
        wb.close()


def test_parse_requires_sheet_and_columns():
    """结构性错误：缺「训练计划」sheet、缺日期列、缺动作名称列均抛 ValueError。"""
    buf = BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = "别的表"
    ws.append(["随便"])
    wb.save(buf)
    with pytest.raises(ValueError, match="缺少工作表"):
        excel_io.parse_workbook(buf.getvalue())

    def _make_with_header(header: list) -> bytes:
        b = BytesIO()
        w = Workbook()
        s = w.active
        s.title = excel_io.SHEET_NAME
        s.append(header)
        s.append(["值"] * len(header))
        w.save(b)
        return b.getvalue()

    with pytest.raises(ValueError, match="计划日期"):
        excel_io.parse_workbook(_make_with_header(["备注", "动作名称", "部位", "重量 kg", "组数", "每组个数", "目标重量 kg"]))

    with pytest.raises(ValueError, match="动作名称"):
        excel_io.parse_workbook(_make_with_header(["计划日期", "训练组编号", "备注", "部位", "重量 kg", "组数", "每组个数", "目标重量 kg"]))


def test_import_groups_rows_by_date_and_group(db):
    """同一天可导入多条训练，各动作按训练组编号关联主记录。

    2026-11-04 起导入落 recorded：status=recorded、end_time 写入；同日期可多次导入再建记录。
    """
    content = _make_workbook([
        ["2026-11-05", "A", "练腿", "深蹲", "腿", 60, 4, "10", 70],
        ["2026-11-05", "A", None, "腿举", "腿", 80, 3, "12", None],
        ["2026-11-05", "A", None, "拉伸", None, None, None, None, None],
        ["2026-11-05", "B", "晚间", "慢跑", None, None, None, None, None],
        ["2026-11-06", "A", "练胸", "卧推", "胸", 40, 3, "10+8+6", 50],
        ["2026-11-06", "A", None, "飞鸟", "胸", None, 3, "12", None],
    ])
    parsed = excel_io.parse_workbook(content)
    valid, errors = excel_io.validate_rows(parsed)
    assert not errors

    groups: dict[tuple[date, str], list[dict]] = {}
    for row in valid:
        groups.setdefault((row["date"], row["group_key"]), []).append(row)
    assert sorted(groups) == [(date(2026, 11, 5), "A"), (date(2026, 11, 5), "B"), (date(2026, 11, 6), "A")]
    assert len(groups[(date(2026, 11, 5), "A")]) == 3

    created = []
    for (day, _group), rows in groups.items():
        remark = next((r["remark"] for r in rows if r["remark"]), None)
        items = [
            PlanItemIn(
                exercise_name=r["exercise_name"], body_part=r["body_part"],
                weight_kg=r["weight_kg"], sets=r["sets"], reps=r["reps"],
                target_weight_kg=r["target_weight_kg"],
            )
            for r in rows
        ]
        created.append(service.create_plan(db, USER, day, items, remark=remark, status=TR_STATUS_RECORDED))

    p1, p_mid, p2 = created
    assert p1.date == date(2026, 11, 5) and p1.status == TR_STATUS_RECORDED and p1.end_time is not None
    assert p1.remark == "练腿"
    assert [i.exercise_name for i in p1.items] == ["深蹲", "腿举", "拉伸"]
    assert [i.sort for i in p1.items] == [1, 2, 3]
    assert p_mid.date == p1.date and p_mid.id != p1.id and p_mid.items[0].exercise_name == "慢跑"
    assert p2.date == date(2026, 11, 6) and p2.remark == "练胸"
    assert p2.items[0].reps == "10+8+6" and p2.items[0].target_weight_kg == 50
    # 同日期多计划：再导一次会再建一条，不覆盖
    service.create_plan(db, USER, date(2026, 11, 5), [PlanItemIn(exercise_name="额外动作")], remark=None, status=TR_STATUS_RECORDED)
    assert len(service.get_plans_by_date(db, USER, date(2026, 11, 5))) == 3


def test_validate_rejects_bad_rows_keeps_good():
    """行级校验：日期为空/格式错、动作名空、重量越界、组数 0 报错，好行不受影响。"""
    content = _make_workbook([
        [None, "A", None, "动作A", "腿", 60, 4, "10", None],
        ["2026-13-99", "A", None, "动作B", "腿", 60, 4, "10", None],
        ["2026-11-05", "A", None, None, "腿", 60, 4, "10", None],
        ["2026-11-05", "A", None, "动作C", "腿", 1500, 4, "10", None],
        ["2026-11-05", "A", None, "动作D", "腿", 60, 0, "10", None],
        ["2026-11-05", "A", None, "动作E", "腿", 60, 4, "10", 60],
    ])
    parsed = excel_io.parse_workbook(content)
    valid, errors = excel_io.validate_rows(parsed)
    assert len(valid) == 1 and valid[0]["exercise_name"] == "动作E"
    reasons = {e["row"]: e["reason"] for e in errors}
    assert reasons[2] == "计划日期不能为空"
    assert "日期格式" in reasons[3]
    assert reasons[4] == "动作名称不能为空"
    assert "超出合理范围" in reasons[5]
    assert "超出合理范围" in reasons[6]


def test_import_parses_times_and_derives_duration(db):
    """开始/结束时间列可留空；填了按计划日期拼成 datetime，训练时长按起止推导。"""
    content = _make_workbook([
        ["2026-11-05", "A", None, "深蹲", "腿", 60, 4, "10", None, "19:00", "20:00"],
        ["2026-11-05", "A", None, "腿举", "腿", 80, 3, "12", None, None, None],
    ])
    parsed = excel_io.parse_workbook(content)
    valid, errors = excel_io.validate_rows(parsed)
    assert not errors
    assert valid[0]["start_time"] == datetime(2026, 11, 5, 19, 0)
    assert valid[0]["end_time"] == datetime(2026, 11, 5, 20, 0)
    assert valid[1]["start_time"] is None          # 同组后续行可留空，取首个非空值

    plan = service.create_plan(
        db, USER, date(2026, 11, 5), [PlanItemIn(exercise_name="深蹲")],
        status=TR_STATUS_RECORDED,
        start_time=valid[0]["start_time"], end_time=valid[0]["end_time"],
    )
    assert plan.duration_s == 3600


def test_import_rejects_reversed_times():
    content = _make_workbook([
        ["2026-11-05", "A", None, "深蹲", "腿", 60, 4, "10", None, "20:00", "19:00"],
    ])
    valid, errors = excel_io.validate_rows(excel_io.parse_workbook(content))
    assert valid == []
    assert errors[0]["column"] == "结束时间"


def test_parse_skips_blank_rows_and_ignores_unknown_columns():
    """空行跳过、未知列忽略、整行空白不产生错误。"""
    content = _make_workbook([
        [None, None, None, None, None, None, None, None, None],
        ["2026-11-05", "A", None, "有效动作", "腿", 60, 4, "10", None],
    ])
    wb = load_workbook(BytesIO(content))
    ws = wb[excel_io.SHEET_NAME]
    ws["M3"] = "未知列的值"   # 表头之外的列（第 13 列），应被忽略
    buf = BytesIO()
    wb.save(buf)
    parsed = excel_io.parse_workbook(buf.getvalue())
    valid, errors = excel_io.validate_rows(parsed)
    assert len(valid) == 1 and valid[0]["exercise_name"] == "有效动作"
    assert not errors

