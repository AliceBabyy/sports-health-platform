"""AI 助手只读工具层单测：全量取数、按范围取数、身份隔离、只读与参数护栏。

覆盖整改要求：所有模块都能一次拉全量，也能按意图只拉一部分；不再有 366 天 / 20 条硬上限。
"""
from datetime import date, datetime, timedelta

import pytest

from app.core.constants import today_local
from app.core.exceptions import AppError
from app.modules.agent.tools import queries
from app.modules.agent.tools.definitions import _resolve_limit, _resolve_range
from app.modules.auth.models import User
from app.modules.body import service as body_service
from app.modules.cycle.models import CycleSetting, DailyPainLog, PeriodRecord
from app.modules.dance.models import DanceRecord
from app.modules.state_record import service as state_service
from app.modules.state_record.schemas import StateRecordIn
from app.modules.swim.models import SwimRecord
from app.modules.training.models import TrainingRecord, TrainingRecordItem

U1, U2 = 1, 2


def _d(day: str) -> date:
    return date.fromisoformat(day)


def _training(day: str, *, user: int = U1, status: str = "recorded", duration_s: int | None = 3600) -> TrainingRecord:
    return TrainingRecord(user_id=user, date=_d(day), status=status, duration_s=duration_s)


def _swim(day: str, *, user: int = U1, status: str = "recorded", distance_m: int = 1000,
          duration_s: int = 1800, calories: float | None = 200) -> SwimRecord:
    return SwimRecord(user_id=user, date=_d(day), status=status, distance_m=distance_m,
                      duration_s=duration_s, calories=calories)


# ---------- 范围与条数护栏 ----------

TODAY = today_local()


def test_resolve_range_defaults_to_full_history():
    assert _resolve_range(None, None, None, TODAY) == (None, None)


def test_resolve_range_days_back_and_validation():
    assert _resolve_range(None, None, 7, TODAY) == (TODAY - timedelta(days=6), TODAY)
    with pytest.raises(AppError):
        _resolve_range(None, None, 0, TODAY)
    with pytest.raises(AppError):
        _resolve_range(_d("2026-11-10"), _d("2026-11-01"), None, TODAY)
    with pytest.raises(AppError):
        _resolve_range(_d("2026-11-01"), None, None, TODAY)


def test_no_upper_bound_on_range_or_limit():
    """整改后不再限制跨度 366 天、条数 20。"""
    start = TODAY - timedelta(days=4000)
    assert _resolve_range(start, TODAY, None, TODAY) == (start, TODAY)
    assert _resolve_range(None, None, 4000, TODAY) == (TODAY - timedelta(days=3999), TODAY)
    assert _resolve_limit(None) is None
    assert _resolve_limit(500) == 500
    with pytest.raises(AppError):
        _resolve_limit(0)


# ---------- 枚举白名单（代码强制，防越界取值） ----------

def test_invalid_enum_arguments_are_rejected(db):
    with pytest.raises(AppError):
        queries.workout_summary(db, U1, None, None, "yoga")
    with pytest.raises(AppError):
        queries.swim_records(db, U1, None, None, status="done")
    with pytest.raises(AppError):
        queries.state_records(db, U1, None, None, "sleep")
    with pytest.raises(AppError):
        queries.body_measurements(db, U1, "bmi", None, None)


# ---------- 运动汇总 ----------

def test_workout_summary_full_history_and_user_isolation(db):
    db.add_all([
        _training("2024-01-05"),
        _swim("2025-06-01"),
        DanceRecord(user_id=U1, date=_d("2026-01-01"), status="planned"),
        _training("2026-01-02", user=U2),  # 他人数据不得混入
    ])
    db.commit()

    result = queries.workout_summary(db, U1, None, None, "all")
    assert result["range"] == {"start": None, "end": None, "scope": "all"}
    assert result["total"]["records"] == 2
    assert result["total"]["plans"] == 1
    assert result["total"]["minutes"] == 60 + 30
    assert result["total"]["kcal"] == 200.0


def test_workout_summary_range_only_counts_window(db):
    db.add_all([_training("2025-01-01"), _training("2026-11-10")])
    db.commit()
    result = queries.workout_summary(db, U1, _d("2026-11-01"), _d("2026-11-30"), "fitness")
    assert result["per_sport"]["fitness"]["records"] == 1


# ---------- 健身明细 ----------

def test_fitness_records_full_pull_includes_items_and_note(db):
    plan = _training("2026-11-01")
    plan.items = [
        TrainingRecordItem(sort=0, exercise_name="卧推", weight_kg=60, sets=3, reps="10+8"),
        TrainingRecordItem(sort=1, exercise_name="深蹲", weight_kg=80, sets=4, reps="8"),
    ]
    db.add(plan)
    db.commit()

    result = queries.fitness_records(db, U1, None, None)
    assert result["count"] == 1
    record = result["records"][0]
    assert record["status"] == "recorded"
    assert record["item_count"] == 2
    assert record["total_sets"] == 7
    # 卧推 60×3×10 + 深蹲 80×4×8
    assert record["total_volume"] == 1800.0 + 2560.0


def test_fitness_records_status_and_limit(db):
    db.add_all([
        _training("2025-01-01", status="planned"),
        _training("2026-10-01"), _training("2026-11-01"), _training("2026-11-05"),
    ])
    db.commit()
    assert queries.fitness_records(db, U1, None, None, status="planned")["count"] == 1
    assert queries.fitness_records(db, U1, None, None, limit=2)["count"] == 2
    assert queries.fitness_records(db, U1, None, None)["count"] == 4


# ---------- 游泳明细（需求 1：允许一次拉全部） ----------

def test_swim_records_can_pull_all_without_cap(db):
    db.add_all([_swim(f"2026-01-{day:02d}") for day in range(1, 26)] + [_swim("2026-02-01", user=U2)])
    db.commit()

    all_rows = queries.swim_records(db, U1, None, None)
    assert all_rows["count"] == 25  # 旧实现上限 20，现在取全量
    assert len(all_rows["records"]) == 25
    assert all_rows["records"][0]["date"] == "2026-01-25"

    limited = queries.swim_records(db, U1, None, None, limit=5)
    assert limited["count"] == 5
    assert limited["range"]["scope"] == "all"


def test_swim_records_range_and_derived_fields(db):
    db.add_all([_swim("2025-05-01"), _swim("2026-11-11", distance_m=2000, duration_s=2400)])
    db.commit()
    result = queries.swim_records(db, U1, _d("2026-11-01"), _d("2026-11-30"))
    assert result["count"] == 1
    record = result["records"][0]
    assert record["pace"] == 2.0  # 2400s / 2000m × 100 / 60 = 2 分/100 米
    assert record["status"] == "recorded"


# ---------- 舞蹈明细 ----------

def test_dance_records_full_pull(db):
    db.add_all([
        DanceRecord(user_id=U1, date=_d("2025-01-01"), status="planned", dance_type="爵士", teacher="A"),
        DanceRecord(user_id=U1, date=_d("2026-11-10"), status="recorded", dance_type="Hiphop", stars=4),
    ])
    db.commit()
    result = queries.dance_records(db, U1, None, None)
    assert result["count"] == 2
    assert result["records"][0]["dance_type"] == "Hiphop"
    assert result["records"][1]["status"] == "planned"


# ---------- 身材 ----------

def test_body_all_merges_four_groups_by_date(db):
    body_service.upsert_group(db, U1, "basic", _d("2026-11-01"), {"weight": 62.0, "body_fat": 18.0})
    body_service.upsert_group(db, U1, "girth", _d("2026-11-01"), {"waist": 74.0})
    body_service.upsert_group(db, U1, "basic", _d("2025-01-01"), {"weight": 70.0})

    result = queries.body_measurements(db, U1, "all", None, None)
    assert result["mode"] == "all"
    assert result["count"] == 2
    assert result["rows"][0]["date"] == "2026-11-01"
    assert result["rows"][0]["values"]["weight"] == 62.0
    assert result["rows"][0]["values"]["waist"] == 74.0


def test_body_single_metric_points(db):
    body_service.upsert_group(db, U1, "basic", _d("2026-10-01"), {"weight": 63.0})
    body_service.upsert_group(db, U1, "basic", _d("2026-11-01"), {"weight": 61.5})

    result = queries.body_measurements(db, U1, "weight", _d("2026-10-15"), None)
    assert result["mode"] == "metric"
    assert result["sample_count"] == 1
    assert result["points"][0]["value"] == 61.5


# ---------- 状态记录 ----------

def test_state_records_full_pull_all_types_and_isolation(db):
    state_service.create_record(db, U1, StateRecordIn(date=_d("2025-01-01"), type="appetite", star=3, remark="尚可"))
    state_service.create_record(db, U1, StateRecordIn(date=_d("2026-11-10"), type="myalgia", star=2))
    state_service.create_record(db, U1, StateRecordIn(date=_d("2026-11-10"), type="inflammation", star=None))
    state_service.create_record(db, U2, StateRecordIn(date=_d("2026-11-10"), type="appetite", star=5))

    result = queries.state_records(db, U1, None, None)
    assert result["count"] == 3
    assert result["per_type"] == {"appetite": 1, "myalgia": 1, "inflammation": 1}
    assert result["records"][0]["date"] == "2026-11-10"

    filtered = queries.state_records(db, U1, None, None, "appetite")
    assert filtered["count"] == 1
    assert filtered["records"][0]["star"] == 3


# ---------- 生理周期 ----------

def test_cycle_records_is_read_only_and_returns_defaults(db):
    result = queries.cycle_records(db, U1, None, None)
    assert result["settings"]["is_default"] is True
    assert result["period_count"] == 0
    # 只读：未设置参考值时不落库 cycle_settings
    assert db.query(CycleSetting).count() == 0


def test_cycle_records_returns_records_pain_and_today(db):
    today = today_local()
    start = today - timedelta(days=4)
    db.add_all([
        CycleSetting(user_id=U1, cycle_length=28, period_length=5),
        PeriodRecord(user_id=U1, start_date=start, end_date=start + timedelta(days=4)),
        DailyPainLog(user_id=U1, log_date=today, pain_level=2),
        DailyPainLog(user_id=U1, log_date=today - timedelta(days=1), pain_level=1),
    ])
    db.commit()

    result = queries.cycle_records(db, U1, None, None)
    assert result["settings"] == {"cycle_length": 28, "period_length": 5, "is_default": False}
    assert result["period_count"] == 1
    assert result["periods"][0]["period_length"] == 5
    assert result["pain_count"] == 2
    assert result["today"]["pain_level"] == 2
    assert result["today"]["cycle_day"] == 5
    assert result["today"]["phase_label"] == "月经期"


# ---------- 个人信息 ----------

def test_profile_info_hides_password(db):
    db.add(User(username="lrx", password_hash="secret-hash", display_name="小鹿", gender="女", age=29))
    db.commit()
    result = queries.profile_info(db, U1)
    assert result["display_name"] == "小鹿"
    assert result["gender"] == "女"
    assert result["age"] == 29
    assert "password_hash" not in result
    assert "username" not in result
