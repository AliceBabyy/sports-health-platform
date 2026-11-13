"""生理周期单测：记录派生长度、分段推算、三态经期、预测边界、段长校验。"""
from datetime import date, timedelta

import pytest

from app.core.constants import (
    PERIOD_STATE_INFERRED,
    PERIOD_STATE_PREDICTED,
    PERIOD_STATE_RECORDED,
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
from app.core.exceptions import AppError
from app.modules.cycle import service

TODAY = date(2026, 11, 12)
ANCHOR = date(2026, 10, 16)


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch):
    monkeypatch.setattr(service, "today_local", lambda: TODAY)


def _cal(db, year, month):
    return {d["date"]: d for d in service.calendar_month(db, 1, year, month)["days"]}


# ---------- 记录派生 ----------
def test_list_periods_derives_lengths(db):
    service.create_period(db, 1, ANCHOR, date(2026, 10, 20))       # 5 天
    service.create_period(db, 1, date(2026, 11, 13), date(2026, 11, 17))
    rows = service.list_periods(db, 1)

    assert rows[0]["start_date"] == "2026-11-13"
    assert rows[0]["period_length"] == 5
    assert rows[0]["cycle_length"] is None        # 没有下一条
    assert rows[1]["period_length"] == 5
    assert rows[1]["cycle_length"] == 28          # 10-16 → 11-13


def test_list_periods_null_period_length_without_end(db):
    service.create_period(db, 1, ANCHOR, None)
    assert service.list_periods(db, 1)[0]["period_length"] is None


def test_create_period_does_not_touch_reference_settings(db):
    service.update_settings(db, 1, 30, 6)
    service.create_period(db, 1, ANCHOR, date(2026, 10, 20))
    setting = service.get_settings(db, 1)
    assert (setting.cycle_length, setting.period_length) == (30, 6)


# ---------- 段内阶段（自适应） ----------
def test_phase_boundaries_28_day_segment(db):
    service.create_period(db, 1, ANCHOR, date(2026, 10, 20))
    october = _cal(db, 2026, 10)
    november = _cal(db, 2026, 11)

    assert october["2026-10-16"]["phase_key"] == PHASE_MENSTRUAL
    assert october["2026-10-20"]["phase_key"] == PHASE_MENSTRUAL
    assert october["2026-10-21"]["phase_key"] == PHASE_FOLLICULAR_PRE
    assert october["2026-10-28"]["phase_key"] == PHASE_FOLLICULAR_PRE   # 排卵前一天
    assert october["2026-10-29"]["phase_key"] == PHASE_OVULATION_DAY    # 28-14=14
    assert october["2026-10-30"]["phase_key"] == PHASE_FOLLICULAR_POST
    assert october["2026-10-31"]["phase_key"] == PHASE_FOLLICULAR_POST
    assert november["2026-11-01"]["phase_key"] == PHASE_LUTEAL_EARLY
    assert november["2026-11-04"]["phase_key"] == PHASE_LUTEAL_EARLY
    assert november["2026-11-05"]["phase_key"] == PHASE_LUTEAL_MID
    assert november["2026-11-08"]["phase_key"] == PHASE_LUTEAL_MID
    assert november["2026-11-09"]["phase_key"] == PHASE_LUTEAL_LATE
    assert november["2026-11-12"]["phase_key"] == PHASE_LUTEAL_LATE


def test_phase_boundaries_shift_with_segment_length(db):
    """段长 30：排卵日随段长推到第 16 天，卵泡期自动拉长。"""
    service.create_period(db, 1, ANCHOR, date(2026, 10, 20))
    service.create_period(db, 1, date(2026, 11, 15), None)  # 10-16 → 11-15 = 30 天
    october = _cal(db, 2026, 10)
    november = _cal(db, 2026, 11)

    assert october["2026-10-30"]["phase_key"] == PHASE_FOLLICULAR_PRE
    assert october["2026-10-31"]["phase_key"] == PHASE_OVULATION_DAY
    assert november["2026-11-01"]["phase_key"] == PHASE_FOLLICULAR_POST
    assert november["2026-11-02"]["phase_key"] == PHASE_FOLLICULAR_POST
    assert november["2026-11-03"]["phase_key"] == PHASE_LUTEAL_EARLY
    assert november["2026-11-06"]["phase_key"] == PHASE_LUTEAL_EARLY


# ---------- 四档 ----------
@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 10, 16), SPORT_REST),
        (date(2026, 10, 19), SPORT_AVERAGE),
        (date(2026, 10, 20), SPORT_GOOD),
        (date(2026, 10, 21), SPORT_HIGH),
        (date(2026, 10, 29), SPORT_HIGH),
        (date(2026, 10, 30), SPORT_HIGH),
        (date(2026, 11, 4), SPORT_GOOD),
        (date(2026, 11, 6), SPORT_GOOD),
        (date(2026, 11, 8), SPORT_AVERAGE),
        (date(2026, 11, 10), SPORT_AVERAGE),
        (date(2026, 11, 11), SPORT_REST),
    ],
)
def test_sport_level_daily(db, day, expected):
    service.create_period(db, 1, ANCHOR, date(2026, 10, 20))
    cal = _cal(db, day.year, day.month)
    assert cal[day.isoformat()]["sport_level"] == expected


def test_sport_level_pain_priority(db):
    service.create_period(db, 1, ANCHOR, date(2026, 10, 20))
    service.set_pain(db, 1, date(2026, 10, 29), 3)
    assert _cal(db, 2026, 10)["2026-10-29"]["sport_level"] == SPORT_REST


# ---------- 三态经期 ----------
def test_recorded_and_no_history_prediction(db):
    """历史月只呈现记录支撑的经期，不出现预测出来的经期。"""
    service.create_period(db, 1, ANCHOR, date(2026, 10, 20))
    service.create_period(db, 1, date(2026, 11, 13), date(2026, 11, 17))

    october = _cal(db, 2026, 10)
    assert october["2026-10-16"]["period_state"] == PERIOD_STATE_RECORDED
    assert october["2026-10-20"]["period_state"] == PERIOD_STATE_RECORDED
    assert october["2026-10-21"]["period_state"] is None
    assert all(d["period_state"] != PERIOD_STATE_PREDICTED for d in october.values())

    november = _cal(db, 2026, 11)
    assert november["2026-11-13"]["period_state"] == PERIOD_STATE_RECORDED
    assert november["2026-11-17"]["period_state"] == PERIOD_STATE_RECORDED
    assert november["2026-11-18"]["period_state"] is None
    assert all(d["period_state"] != PERIOD_STATE_PREDICTED for d in november.values())


def test_predicted_only_extends_one_segment(db):
    service.create_period(db, 1, ANCHOR, date(2026, 10, 20))
    december = _cal(db, 2026, 12)
    assert december["2026-12-10"]["phase_key"] == PHASE_LUTEAL_LATE   # 预测段最后一天
    assert december["2026-12-11"]["phase_key"] is None                # 再往后留白
    # 再下一段不再推算
    assert all(d["phase_key"] is None for d in _cal(db, 2027, 1).values())
    assert service.next_period_date(db, 1) == date(2026, 11, 13)
    november = _cal(db, 2026, 11)
    assert november["2026-11-13"]["period_state"] == PERIOD_STATE_PREDICTED
    assert november["2026-11-17"]["period_state"] == PERIOD_STATE_PREDICTED


def test_overdue_beyond_grace_drops_prediction(db, monkeypatch):
    monkeypatch.setattr(service, "today_local", lambda: date(2026, 12, 30))
    service.create_period(db, 1, ANCHOR, date(2026, 10, 20))
    cal = service.calendar_month(db, 1, 2026, 12)
    assert cal["overview"]["overdue_days"] == 47
    assert all(d["phase_key"] is None for d in cal["days"])


def test_inferred_period_state_for_missed_records(db):
    """10-16 与 12-16 间隔 61 天 → 判漏记，按参考周期等分两段补推。"""
    service.create_period(db, 1, ANCHOR, date(2026, 10, 20))
    service.create_period(db, 1, date(2026, 12, 16), date(2026, 12, 20))
    november = _cal(db, 2026, 11)
    assert november["2026-11-16"]["period_state"] == PERIOD_STATE_INFERRED
    assert november["2026-11-20"]["period_state"] == PERIOD_STATE_INFERRED
    assert november["2026-11-15"]["period_state"] is None
    assert november["2026-11-16"]["period_label"] == "推算经期"


def test_gap_over_three_months_leaves_blank(db):
    service.create_period(db, 1, date(2026, 6, 1), date(2026, 6, 5))
    service.create_period(db, 1, date(2026, 10, 16), date(2026, 10, 20))
    july = _cal(db, 2026, 7)
    assert all(d["phase_key"] is None for d in july.values())


# ---------- 0 / 1 条记录 ----------
def test_no_records_no_phase(db):
    cal = service.calendar_month(db, 1, 2026, 11)
    assert cal["overview"]["has_records"] is False
    assert cal["overview"]["next_period"] is None
    assert all(d["phase_key"] is None for d in cal["days"])


def test_single_record_uses_reference_for_current_and_next(db):
    service.update_settings(db, 1, 30, 5)
    service.create_period(db, 1, ANCHOR, None)
    november = _cal(db, 2026, 11)
    assert november["2026-11-12"]["phase_key"] is not None
    assert november["2026-11-15"]["phase_key"] == PHASE_MENSTRUAL   # 预测段按参考经期
    assert service.next_period_date(db, 1) == ANCHOR + timedelta(days=30)


# ---------- 段长校验 ----------
def test_validate_rejects_too_short_gap(db):
    service.create_period(db, 1, ANCHOR, date(2026, 10, 20))
    with pytest.raises(AppError) as exc:
        service.validate_period_bounds(db, 1, ANCHOR + timedelta(days=21), None)
    assert "疑似同一次月经" in str(exc.value)


def test_validate_rejects_too_long_period(db):
    with pytest.raises(AppError):
        service.validate_period_bounds(db, 1, ANCHOR, ANCHOR + timedelta(days=8))  # 9 天 > 8
    with pytest.raises(AppError):
        service.validate_period_bounds(db, 1, ANCHOR, TODAY + timedelta(days=1))
    service.validate_period_bounds(db, 1, ANCHOR, ANCHOR + timedelta(days=4))     # 5 天合法


def test_update_period_can_clear_end_date(db):
    row = service.create_period(db, 1, ANCHOR, date(2026, 10, 20))
    unchanged = service.update_period(db, 1, row.id, None, None)
    assert unchanged.end_date == date(2026, 10, 20)
    updated = service.update_period(db, 1, row.id, ANCHOR, None, update_end=True)
    assert updated.end_date is None
