"""生理周期单测：七阶段、逐日四档状态、疼痛优先级、预测与取模。"""
from datetime import date, timedelta

import pytest

from app.core.constants import (
    PHASE_FOLLICULAR_POST,
    PHASE_FOLLICULAR_PRE,
    PHASE_LUTEAL_EARLY,
    PHASE_LUTEAL_LATE,
    PHASE_LUTEAL_MID,
    PHASE_MENSTRUAL,
    PHASE_OVULATION_DAY,
    SPORT_AVERAGE,
    SPORT_GOOD,
    SPORT_HIGH,
    SPORT_REST,
)
from app.modules.cycle import service

ANCHOR = date(2026, 10, 16)  # 月经首日
CL, PL = 28, 5               # 周期 28 / 经期 5


def test_phase_boundaries():
    # 月经期 1~5
    assert service.phase_for(ANCHOR, ANCHOR, CL, PL) == PHASE_MENSTRUAL
    assert service.phase_for(ANCHOR + timedelta(days=4), ANCHOR, CL, PL) == PHASE_MENSTRUAL
    # 排卵期前期 6~13（排卵日=14）
    assert service.phase_for(ANCHOR + timedelta(days=5), ANCHOR, CL, PL) == PHASE_FOLLICULAR_PRE
    assert service.phase_for(ANCHOR + timedelta(days=12), ANCHOR, CL, PL) == PHASE_FOLLICULAR_PRE
    # 排卵日 N=14 → 10-29
    assert service.phase_for(ANCHOR + timedelta(days=13), ANCHOR, CL, PL) == PHASE_OVULATION_DAY
    # 排卵期后期 15~16
    assert service.phase_for(ANCHOR + timedelta(days=14), ANCHOR, CL, PL) == PHASE_FOLLICULAR_POST
    assert service.phase_for(ANCHOR + timedelta(days=15), ANCHOR, CL, PL) == PHASE_FOLLICULAR_POST
    # 黄体期前期 17~20
    assert service.phase_for(ANCHOR + timedelta(days=16), ANCHOR, CL, PL) == PHASE_LUTEAL_EARLY
    assert service.phase_for(ANCHOR + timedelta(days=19), ANCHOR, CL, PL) == PHASE_LUTEAL_EARLY
    # 黄体期中期 21~24
    assert service.phase_for(ANCHOR + timedelta(days=20), ANCHOR, CL, PL) == PHASE_LUTEAL_MID
    assert service.phase_for(ANCHOR + timedelta(days=23), ANCHOR, CL, PL) == PHASE_LUTEAL_MID
    # 黄体期后期 25~28
    assert service.phase_for(ANCHOR + timedelta(days=24), ANCHOR, CL, PL) == PHASE_LUTEAL_LATE
    assert service.phase_for(ANCHOR + timedelta(days=27), ANCHOR, CL, PL) == PHASE_LUTEAL_LATE


def test_phase_cycle_wrap():
    # 下一周期第 1 天（第 29 天）→ 月经期；负数日期回卷到黄体后期
    assert service.phase_for(ANCHOR + timedelta(days=28), ANCHOR, CL, PL) == PHASE_MENSTRUAL
    assert service.phase_for(ANCHOR - timedelta(days=1), ANCHOR, CL, PL) == PHASE_LUTEAL_LATE


def test_effective_day_number():
    assert service.effective_day_number(ANCHOR, ANCHOR, CL) == 1
    assert service.effective_day_number(ANCHOR + timedelta(days=13), ANCHOR, CL) == 14
    assert service.effective_day_number(ANCHOR + timedelta(days=27), ANCHOR, CL) == 28
    assert service.effective_day_number(ANCHOR + timedelta(days=28), ANCHOR, CL) == 1


@pytest.mark.parametrize(
    ("cycle_day", "expected"),
    [
        (1, SPORT_REST), (3, SPORT_REST), (4, SPORT_AVERAGE), (5, SPORT_GOOD),
        (6, SPORT_HIGH), (14, SPORT_HIGH), (16, SPORT_HIGH),
        (17, SPORT_GOOD), (20, SPORT_GOOD), (21, SPORT_GOOD), (22, SPORT_GOOD),
        (23, SPORT_AVERAGE), (24, SPORT_AVERAGE), (25, SPORT_AVERAGE),
        (26, SPORT_AVERAGE), (27, SPORT_REST), (28, SPORT_REST),
    ],
)
def test_sport_level_daily_boundaries(cycle_day, expected):
    phase = service.phase_for(ANCHOR + timedelta(days=cycle_day - 1), ANCHOR, CL, PL)
    assert service.sport_level_for(phase, cycle_day, CL, PL, 0) == expected


def test_sport_level_pain_priority():
    assert service.sport_level_for(PHASE_OVULATION_DAY, 14, CL, PL, 2) == SPORT_REST
    assert service.sport_level_for(PHASE_MENSTRUAL, 5, CL, PL, 3) == SPORT_REST
    assert service.sport_level_for(PHASE_LUTEAL_MID, 22, CL, PL, 1) == SPORT_GOOD


def test_sport_level_variable_cycle_length():
    # 30 天周期排卵日=16；黄体中期第 2/3 天、黄体后期第 2/3 天仍按相对日序切换。
    assert service.sport_level_for(PHASE_LUTEAL_MID, 24, 30, 5, 0) == SPORT_GOOD
    assert service.sport_level_for(PHASE_LUTEAL_MID, 25, 30, 5, 0) == SPORT_AVERAGE
    assert service.sport_level_for(PHASE_LUTEAL_LATE, 28, 30, 5, 0) == SPORT_AVERAGE
    assert service.sport_level_for(PHASE_LUTEAL_LATE, 29, 30, 5, 0) == SPORT_REST


def test_next_period_prediction(db, monkeypatch):
    monkeypatch.setattr(service, "today_local", lambda: date(2026, 11, 4))
    service.create_period(db, 1, ANCHOR, None, None, None)
    assert service.next_period_date(db, 1) == ANCHOR + timedelta(days=CL)


def test_calendar_month_phase_and_pain(db, monkeypatch):
    monkeypatch.setattr(service, "today_local", lambda: date(2026, 11, 4))
    service.create_period(db, 1, ANCHOR, None, None, None)
    service.set_pain(db, 1, ANCHOR + timedelta(days=13), 3)  # 排卵日疼痛3 → 休息
    cal = service.calendar_month(db, 1, 2026, 10)
    by_date = {d["date"]: d for d in cal["days"]}
    assert by_date["2026-10-29"]["phase_key"] == PHASE_OVULATION_DAY
    assert by_date["2026-10-29"]["sport_level"] == SPORT_REST  # 疼痛≥2 最高优先
    assert by_date["2026-10-29"]["pain_level"] == 3
    assert by_date["2026-10-16"]["is_period"] is True
    assert cal["overview"]["next_period"] == (ANCHOR + timedelta(days=CL)).isoformat()


def test_calendar_exposes_four_daily_levels(db, monkeypatch):
    monkeypatch.setattr(service, "today_local", lambda: date(2026, 11, 4))
    service.create_period(db, 1, ANCHOR, None, None, None)
    october = {day["cycle_day"]: day for day in service.calendar_month(db, 1, 2026, 10)["days"] if day["cycle_day"]}
    november = {day["cycle_day"]: day for day in service.calendar_month(db, 1, 2026, 11)["days"] if day["cycle_day"]}
    assert [october[n]["sport_level"] for n in (3, 4, 5, 6)] == [SPORT_REST, SPORT_AVERAGE, SPORT_GOOD, SPORT_HIGH]
    assert [november[n]["sport_level"] for n in (22, 23, 26, 27)] == [SPORT_GOOD, SPORT_AVERAGE, SPORT_AVERAGE, SPORT_REST]


def test_calendar_uses_historical_record_for_each_day(db, monkeypatch):
    monkeypatch.setattr(service, "today_local", lambda: date(2026, 11, 4))
    service.create_period(db, 1, date(2026, 9, 18), None, None, None)
    service.create_period(db, 1, ANCHOR, None, None, None)
    days = {day["date"]: day for day in service.calendar_month(db, 1, 2026, 10)["days"]}
    assert days["2026-10-01"]["phase_key"] is not None
    assert days["2026-10-16"]["cycle_day"] == 1
    assert days["2026-10-16"]["is_recorded_start"] is True


def test_future_record_does_not_change_today_or_next_prediction(db, monkeypatch):
    monkeypatch.setattr(service, "today_local", lambda: date(2026, 11, 4))
    service.create_period(db, 1, ANCHOR, None, None, None)
    service.create_period(db, 1, date(2026, 12, 1), None, None, None)
    assert service.get_anchor_date(db, 1) == ANCHOR
    assert service.next_period_date(db, 1) == date(2026, 11, 13)


def test_next_prediction_rolls_forward(db, monkeypatch):
    monkeypatch.setattr(service, "today_local", lambda: date(2027, 1, 1))
    service.create_period(db, 1, ANCHOR, None, None, None)
    assert service.next_period_date(db, 1) == date(2027, 1, 8)


def test_update_period_can_clear_end_date(db):
    row = service.create_period(db, 1, ANCHOR, date(2026, 10, 20), None, None)
    unchanged = service.update_period(db, 1, row.id, None, None)
    assert unchanged.end_date == date(2026, 10, 20)
    updated = service.update_period(db, 1, row.id, ANCHOR, None, update_end=True)
    assert updated.end_date is None
