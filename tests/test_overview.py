"""跨运动总览单测（2026-11）：日/周/月聚合口径、单日详情、计划态不计入记录。"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.core.constants import TR_STATUS_PLANNED, TR_STATUS_RECORDED, monday_of, today_local
from app.modules.dance import service as dance_service
from app.modules.dance.schemas import DanceRecordIn
from app.modules.overview import service as overview
from app.modules.swim import service as swim_service
from app.modules.swim.schemas import SwimRecordIn
from app.modules.training import service as training_service
from app.modules.training.schemas import PlanItemIn

USER = 1

ITEM = PlanItemIn(exercise_name="杠铃深蹲", body_part="腿", weight_kg=70, sets=5, reps="8")


def _seed(db):
    """周一：健身 1计划+1记录(30min)、游泳 1计划+1记录(30min/120kcal)、舞蹈 1计划+1记录(60min/200kcal)。"""
    monday = monday_of(today_local())
    training_service.create_plan(db, USER, monday, [ITEM])
    p2 = training_service.create_plan(db, USER, monday, [ITEM])
    # 直接落 recorded（绕过「仅当日可保存」校验，本周一 ≠ 今天时仍成立）：started 30 分钟前 → saved 现在
    p2.status = TR_STATUS_RECORDED
    p2.started_at = datetime.now() - timedelta(minutes=30)
    p2.saved_at = datetime.now()
    db.commit()

    swim_service.create_record(
        db,
        USER,
        SwimRecordIn(
            record_date=monday, status=TR_STATUS_PLANNED,
            distance_m=1000, duration_s=1800, main_stroke="freestyle", remark="练换气",
        ),
    )
    swim_service.create_record(
        db,
        USER,
        SwimRecordIn(
            record_date=monday, status=TR_STATUS_RECORDED, distance_m=1500, duration_s=1800,
            calories=Decimal("120"),
        ),
    )
    dance_service.create_record(
        db,
        USER,
        DanceRecordIn(record_date=monday, status=TR_STATUS_PLANNED, dance_type="爵士", stars=4, remark="练爆发力"),
    )
    dance_service.create_record(
        db,
        USER,
        DanceRecordIn(
            record_date=monday, status=TR_STATUS_RECORDED, dance_type="爵士", stars=4,
            duration_s=3600, calories=Decimal("200"),
        ),
    )
    return monday


def test_week_aggregate_counts(db):
    monday = _seed(db)
    res = overview.aggregate(db, USER, "week", today_local())
    assert res["granularity"] == "week"
    assert len(res["days"]) == 7
    assert res["start"] == monday.isoformat()
    day0 = res["days"][0]
    assert day0["date"] == monday.isoformat()
    assert day0["sports"]["fitness"] == {"plans": 1, "records": 1, "minutes": 30, "kcal": 0.0}
    assert day0["sports"]["swim"] == {"plans": 1, "records": 1, "minutes": 30, "kcal": 120.0}
    assert day0["sports"]["dance"] == {"plans": 1, "records": 1, "minutes": 60, "kcal": 200.0}
    # 汇总卡：计划=3、记录=3、时长=120、热量=320（健身无热量字段不参与）
    s = res["stats"]
    assert s["plans"] == 3 and s["records"] == 3 and s["minutes"] == 120 and s["kcal"] == 320.0
    assert s["days"] == 1
    assert s["per_sport"]["fitness"]["minutes"] == 30
    assert s["per_sport"]["swim"]["kcal"] == 120.0
    # 图表序列
    assert res["chart"]["labels"] == ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    assert res["chart"]["fitness"][0] == 30 and res["chart"]["swim"][0] == 30 and res["chart"]["dance"][0] == 60
    assert all(v == 0 for v in res["chart"]["fitness"][1:])
    assert all(v == 0 for v in res["chart"]["swim"][1:])


def test_day_aggregate_single_day(db):
    monday = _seed(db)
    res = overview.aggregate(db, USER, "day", monday)
    assert len(res["days"]) == 1
    assert res["days"][0]["sports"]["dance"]["records"] == 1
    assert res["chart"] is None


def test_month_aggregate_spans_days(db):
    monday = _seed(db)
    res = overview.aggregate(db, USER, "month", monday)
    from calendar import monthrange

    _, last = monthrange(monday.year, monday.month)
    assert len(res["days"]) == last
    row = next(d for d in res["days"] if d["date"] == monday.isoformat())
    assert row["sports"]["fitness"]["records"] == 1
    assert res["stats"]["records"] == 3
    # 图表按月内每日序列（labels=日号），周一当日分钟值落在对应索引
    assert res["chart"] is not None and len(res["chart"]["labels"]) == last
    idx = monday.day - 1
    assert res["chart"]["labels"][idx] == str(monday.day)
    assert res["chart"]["fitness"][idx] == 30
    assert res["chart"]["swim"][idx] == 30
    assert res["chart"]["dance"][idx] == 60


def test_day_detail_includes_status_and_fields(db):
    monday = _seed(db)
    detail = overview.day_detail(db, USER, monday)
    assert detail["date"] == monday.isoformat()
    assert len(detail["fitness"]) == 2
    assert len(detail["swim"]) == 2 and len(detail["dance"]) == 2
    planned_swim = next(r for r in detail["swim"] if r["status"] == TR_STATUS_PLANNED)
    assert planned_swim["distance_m"] == 1000
    assert planned_swim["main_stroke"] == "freestyle"
    assert planned_swim["remark"] == "练换气"
    recorded_swim = next(r for r in detail["swim"] if r["status"] == TR_STATUS_RECORDED)
    assert recorded_swim["distance_m"] == 1500
    planned_dance = next(r for r in detail["dance"] if r["status"] == TR_STATUS_PLANNED)
    assert planned_dance["dance_type"] == "爵士"
    assert planned_dance["stars"] == 4
    assert planned_dance["remark"] == "练爆发力"
    # 空日期：三运动均为空列表
    empty = overview.day_detail(db, USER, date(2020, 1, 1))
    assert empty["fitness"] == [] and empty["swim"] == [] and empty["dance"] == []
