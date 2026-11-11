"""健身训练 JSON 导入单测（2026-11-04 新增：逐计划校验 / 失败计划跳过不阻断）。

2026-11-04 改版：导入数据 status 直接为 recorded（训练记录，写 end_time），不再经 planned。
2026-11-07 改版：计划对象支持可选 start_time / end_time。
"""
from datetime import date, datetime

from app.core.constants import TR_STATUS_RECORDED
from app.modules.training import json_import, service

USER = 1


def _raw_plans() -> list:
    return [
        {
            "date": "2026-11-07",
            "remark": "练胸",
            "items": [
                {"exercise_name": "杠铃卧推", "body_part": "胸", "weight_kg": 40, "sets": 3, "reps": "10+8+6", "target_weight_kg": 50},
                {"exercise_name": "哑铃飞鸟", "body_part": "胸", "weight_kg": 15, "sets": 3, "reps": "12"},
            ],
        },
        {
            "date": "2026-11-08",
            "remark": None,
            "items": [{"exercise_name": "杠铃深蹲", "body_part": "腿", "weight_kg": 70, "sets": 4, "reps": "8", "target_weight_kg": 80}],
        },
    ]


def test_json_import_valid_plans(db):
    """正常导入：每个有效计划新建一条记录（status=recorded、end_time 写入），备注与动作字段落库正确。"""
    valid, errors = json_import.validate_json_plans(_raw_plans())
    assert not errors
    assert len(valid) == 2

    created = []
    for plan_in in valid:
        created.append(service.create_plan(db, USER, plan_in.date, plan_in.items, remark=plan_in.remark, status=TR_STATUS_RECORDED))
    p1, p2 = sorted(created, key=lambda p: p.date)
    assert p1.date == date(2026, 11, 7) and p1.remark == "练胸"
    assert p1.status == TR_STATUS_RECORDED and p1.end_time is not None
    assert [i.exercise_name for i in p1.items] == ["杠铃卧推", "哑铃飞鸟"]
    assert p1.items[0].reps == "10+8+6" and p1.items[0].target_weight_kg == 50
    assert p2.date == date(2026, 11, 8) and p2.remark is None
    assert p2.items[0].weight_kg == 70


def test_json_import_accepts_times(db):
    """计划级起止时间可选；给了就落库，并按起止推导时长。"""
    valid, errors = json_import.validate_json_plans([
        {"date": "2026-11-09", "start_time": "2026-11-09T19:00:00", "end_time": "2026-11-09T20:00:00",
         "items": [{"exercise_name": "杠铃深蹲"}]},
    ])
    assert not errors
    plan = service.create_plan(
        db, USER, valid[0].date, valid[0].items, status=TR_STATUS_RECORDED,
        start_time=valid[0].start_time, end_time=valid[0].end_time,
    )
    assert plan.start_time == datetime(2026, 11, 9, 19, 0)
    assert plan.end_time == datetime(2026, 11, 9, 20, 0)
    assert plan.duration_s == 3600


def test_json_import_accepts_metrics(db):
    """计划对象支持平均心率 / 最大心率 / 热量；给了就落库。"""
    valid, errors = json_import.validate_json_plans([
        {"date": "2026-11-10", "avg_heart_rate": 132, "max_heart_rate": 168, "calories": 320.5,
         "items": [{"exercise_name": "杠铃深蹲"}]},
    ])
    assert not errors
    plan = service.create_plan(
        db, USER, valid[0].date, valid[0].items, status=TR_STATUS_RECORDED,
        avg_heart_rate=valid[0].avg_heart_rate, max_heart_rate=valid[0].max_heart_rate,
        calories=valid[0].calories,
    )
    assert plan.avg_heart_rate == 132 and plan.max_heart_rate == 168
    assert float(plan.calories) == 320.5


def test_json_import_rejects_bad_heart_rate():
    """心率越界按字段返回明细。"""
    valid, errors = json_import.validate_json_plans([
        {"date": "2026-11-10", "avg_heart_rate": 0, "items": [{"exercise_name": "深蹲"}]},
    ])
    assert not valid
    assert errors[0]["column"] == "平均心率" and "超出合理范围" in errors[0]["reason"]


def test_json_import_bad_plans_skipped(db):
    """失败计划跳过：日期格式错、items 空、动作名空均产出明细，好计划照常建。"""
    raw = [
        {"date": "2026-13-99", "items": [{"exercise_name": "A"}]},        # 日期格式错
        {"date": "2026-11-09", "items": []},                             # 动作列表空
        {"date": "2026-11-09", "items": [{"exercise_name": ""}]},        # 动作名空
        {"date": "2026-11-09", "remark": "好计划", "items": [{"exercise_name": "有效动作"}]},
    ]
    valid, errors = json_import.validate_json_plans(raw)
    assert len(valid) == 1 and valid[0].remark == "好计划"
    assert len(errors) == 3
    rows = {e["row"] for e in errors}
    assert rows == {1, 2, 3}
    by_row = {e["row"]: e for e in errors}
    assert by_row[1]["column"] == "计划日期" and "日期格式" in by_row[1]["reason"]
    assert by_row[2]["column"] == "动作列表" and "至少" in by_row[2]["reason"]
    assert by_row[3]["column"] == "动作名称（第 1 个动作）" and "不能为空" in by_row[3]["reason"]

    created = [service.create_plan(db, USER, p.date, p.items, remark=p.remark, status=TR_STATUS_RECORDED) for p in valid]
    assert len(created) == 1
    assert created[0].status == TR_STATUS_RECORDED
    assert len(service.get_plans_by_date(db, USER, date(2026, 11, 9))) == 1


def test_json_import_persist_keeps_empty_end_time(db):
    """落库函数不再补当前时刻：没给结束时间就留空，时长也为空（2026-11-10）。"""
    valid, errors = json_import.validate_json_plans([
        {"date": "2026-11-09", "items": [{"exercise_name": "杠铃深蹲"}]},
    ])
    assert not errors
    ids, _ = json_import.persist_valid_plans(db, USER, valid)
    plan = service.get_plan(db, USER, ids[0])
    assert plan.end_time is None and plan.start_time is None and plan.duration_s is None


def test_json_import_rejects_non_object_and_oversize_fields():
    """非对象计划项报错；超上限的字段（动作名/备注过长、组数 0）也产出明细；重量不限值。"""
    raw = [
        "不是一个对象",
        {
            "date": "2026-11-10",
            "remark": "x" * 300,
            "items": [
                {"exercise_name": "长动作名" * 40, "body_part": "部位" * 20, "weight_kg": 1500, "sets": 0},
            ],
        },
    ]
    valid, errors = json_import.validate_json_plans(raw)
    assert not valid
    reasons = {e["column"]: e["reason"] for e in errors}
    assert reasons["计划"] == "计划项必须是对象"
    assert "过长" in reasons["备注"]
    assert "过长" in reasons["动作名称（第 1 个动作）"]
    assert "重量 kg（第 1 个动作）" not in reasons   # 重量任意数值，不做范围限值

