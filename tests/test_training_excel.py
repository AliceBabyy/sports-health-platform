"""健身训练 Excel 导入单测（2026-11-04 新增：模板生成 / 解析 / 行级校验 / 按日期分组建记录）。

2026-11-04 改版：导入数据 status 直接为 recorded（训练记录，写 saved_at），不再经 planned。
"""
from datetime import date
from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from app.core.constants import TR_STATUS_RECORDED
from app.modules.training import excel_io, service
from app.modules.training.schemas import PlanItemIn

USER = 1

HEADERS = ["计划日期", "备注", "动作名称", "部位", "重量 kg", "组数", "每组个数", "目标重量 kg"]


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
        excel_io.parse_workbook(_make_with_header(["计划日期", "备注", "部位", "重量 kg", "组数", "每组个数", "目标重量 kg"]))


def test_import_groups_rows_by_date(db):
    """按日期分组建记录：同日期 3 行 → 1 条记录 3 动作；两日期 → 2 条记录，动作按行序。

    2026-11-04 起导入落 recorded：status=recorded、saved_at 写入；同日期可多次导入再建记录。
    """
    content = _make_workbook([
        ["2026-11-05", "练腿", "深蹲", "腿", 60, 4, "10", 70],
        ["2026-11-05", None, "腿举", "腿", 80, 3, "12", None],
        ["2026-11-05", None, "拉伸", None, None, None, None, None],
        ["2026-11-06", "练胸", "卧推", "胸", 40, 3, "10+8+6", 50],
        ["2026-11-06", None, "飞鸟", "胸", None, 3, "12", None],
    ])
    parsed = excel_io.parse_workbook(content)
    valid, errors = excel_io.validate_rows(parsed)
    assert not errors

    groups: dict[date, list[dict]] = {}
    for row in valid:
        groups.setdefault(row["plan_date"], []).append(row)
    assert sorted(groups) == [date(2026, 11, 5), date(2026, 11, 6)]
    assert len(groups[date(2026, 11, 5)]) == 3

    created = []
    for plan_date, rows in groups.items():
        remark = next((r["remark"] for r in rows if r["remark"]), None)
        items = [
            PlanItemIn(
                exercise_name=r["exercise_name"], body_part=r["body_part"],
                weight_kg=r["weight_kg"], sets=r["sets"], reps=r["reps"],
                target_weight_kg=r["target_weight_kg"],
            )
            for r in rows
        ]
        created.append(service.create_plan(db, USER, plan_date, items, remark=remark, status=TR_STATUS_RECORDED))

    p1, p2 = sorted(created, key=lambda p: p.plan_date)
    assert p1.plan_date == date(2026, 11, 5) and p1.status == TR_STATUS_RECORDED and p1.saved_at is not None
    assert p1.remark == "练腿"
    assert [i.exercise_name for i in p1.items] == ["深蹲", "腿举", "拉伸"]
    assert [i.sort for i in p1.items] == [1, 2, 3]
    assert p2.plan_date == date(2026, 11, 6) and p2.remark == "练胸"
    assert p2.items[0].reps == "10+8+6" and p2.items[0].target_weight_kg == 50
    # 同日期多计划：再导一次会再建一条，不覆盖
    service.create_plan(db, USER, date(2026, 11, 5), [PlanItemIn(exercise_name="额外动作")], remark=None, status=TR_STATUS_RECORDED)
    assert len(service.get_plans_by_date(db, USER, date(2026, 11, 5))) == 2


def test_validate_rejects_bad_rows_keeps_good():
    """行级校验：日期为空/格式错、动作名空、重量越界、组数 0 报错，好行不受影响。"""
    content = _make_workbook([
        [None, None, "动作A", "腿", 60, 4, "10", None],                     # 日期空
        ["2026-13-99", None, "动作B", "腿", 60, 4, "10", None],             # 日期格式错
        ["2026-11-05", None, None, "腿", 60, 4, "10", None],                # 动作名空
        ["2026-11-05", None, "动作C", "腿", 1500, 4, "10", None],           # 重量越界
        ["2026-11-05", None, "动作D", "腿", 60, 0, "10", None],             # 组数越界
        ["2026-11-05", None, "动作E", "腿", 60, 4, "10", 60],               # 正常
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


def test_parse_skips_blank_rows_and_ignores_unknown_columns():
    """空行跳过、未知列忽略、整行空白不产生错误。"""
    content = _make_workbook([
        [None, None, None, None, None, None, None, None],                   # 整行空白
        ["2026-11-05", None, "有效动作", "腿", 60, 4, "10", None],
    ])
    wb = load_workbook(BytesIO(content))
    ws = wb[excel_io.SHEET_NAME]
    ws["I3"] = "未知列的值"  # 第 9 列不在模板中，且只加在有效数据行
    buf = BytesIO()
    wb.save(buf)
    parsed = excel_io.parse_workbook(buf.getvalue())
    valid, errors = excel_io.validate_rows(parsed)
    assert len(valid) == 1 and valid[0]["exercise_name"] == "有效动作"
    assert not errors
