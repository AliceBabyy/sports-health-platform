"""趋势聚合单测（BD-10~14）：锚点窗口均值、null 断线、同日覆盖取最后（4 表：体重在 body_basic_records）。"""
from datetime import date, timedelta

from app.core.constants import BODY_COLUMNS, today_local
from app.modules.body import trend_service
from app.modules.body.models import BodyBasicRecord

USER = 1


def _add(db, day: date, value: float, metric="weight"):
    db.add(BodyBasicRecord(user_id=USER, record_date=day, **{BODY_COLUMNS[metric]: value}))
    db.commit()


def test_week_points_today_values_and_null(db):
    today = today_local()
    monday = today - timedelta(days=today.weekday())
    _add(db, monday, 60.0)
    _add(db, today, 61.0)
    points = trend_service.build_trend(db, USER, "weight", "week")["points"]
    assert len(points) == 7
    assert points[0]["date"] == monday.isoformat() and points[0]["value"] == 60.0
    assert points[6]["date"] == (monday + timedelta(days=6)).isoformat()
    # 中间无记录 → null（断线点）
    for p in points[1:6]:
        if p["date"] != today.isoformat():
            assert p["value"] is None


def test_same_day_multiple_take_last(db):
    """同日重复添加同组 → 覆盖取最后一次值。"""
    today = today_local()
    for v in (60.0, 60.5, 61.0):
        service_upsert(db, today, v)
    points = trend_service.build_trend(db, USER, "weight", "month")["points"]
    target = next(p for p in points if p["date"] == today.isoformat())
    assert target["value"] == 61.0


def service_upsert(db, day: date, value: float, metric="weight"):
    from app.modules.body import service as body_service

    body_service.upsert_group(db, USER, "basic", day, {metric: value})


def test_half_year_window_average(db):
    today = today_local()
    anchor = today.replace(day=1)  # 本月 1 号锚点
    if anchor > today:
        return
    _add(db, anchor, 60.0)
    _add(db, anchor - timedelta(days=5), 61.0)
    points = trend_service.build_trend(db, USER, "weight", "half_year")["points"]
    assert len(points) == 18
    first = next(p for p in points if p["date"] == anchor.isoformat())
    assert first["value"] == 60.5


def test_year_window_average_and_null(db):
    today = today_local()
    anchor = today.replace(day=15) if today.day >= 15 else today.replace(day=1)
    if anchor > today:
        anchor = today.replace(day=1)
    _add(db, anchor, 65.0)
    points = trend_service.build_trend(db, USER, "weight", "year")["points"]
    assert len(points) <= 24
    first = next(p for p in points if p["date"] == anchor.isoformat())
    assert first["value"] == 65.0
    # 其余锚点窗口无记录 → null
    for p in points:
        if p["date"] != anchor.isoformat():
            assert p["value"] is None


def test_unknown_range_raises(db):
    import pytest

    with pytest.raises(ValueError):
        trend_service.build_trend(db, USER, "weight", "daily")
