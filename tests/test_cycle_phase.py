"""生理周期单测：记录派生长度、分段推算、三态经期、预测边界、段长校验。"""
from datetime import date, timedelta

import pytest

from app.core.constants import (
    PERIOD_STATE_INFERRED,
    PERIOD_STATE_PREDICTED,
    PERIOD_STATE_RECORDED,
    PHASE_FOLLICULAR_POST,
    PHASE_FOLLICULAR_PRE,
    PHASE_HORMONE,
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
from app.modules.cycle.models import PeriodLog

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
    service.set_pain(db, 1, date(2026, 10, 19), 3)  # 经期第 4 天，默认状态一般
    assert _cal(db, 2026, 10)["2026-10-19"]["sport_level"] == SPORT_REST


def test_pain_only_writable_in_recorded_period(db):
    record = service.create_period(db, 1, ANCHOR, date(2026, 10, 20))
    with pytest.raises(AppError):
        service.set_pain(db, 1, date(2026, 10, 29), 2)  # 排卵日不可记疼痛
    log = service.set_pain(db, 1, date(2026, 10, 18), 2)
    assert log.pain_level == 2
    assert log.period_id == record.id
    assert log.note is None


def test_note_on_period_and_non_period_day(db):
    record = service.create_period(db, 1, ANCHOR, date(2026, 10, 20))

    # 经期日：note 正常存，并归属该条月经记录；未填疼痛为 null
    log = service.set_note(db, 1, ANCHOR, "经期第一天")
    assert (log.note, log.period_id, log.pain_level) == ("经期第一天", record.id, None)

    # 非经期日：note 正常存，pain_level / period_id 为 null
    log2 = service.set_note(db, 1, date(2026, 10, 29), "排卵日记录")
    assert (log2.note, log2.pain_level, log2.period_id) == ("排卵日记录", None, None)

    # 经期先记疼痛再写 note：疼痛与归属保留
    service.set_pain(db, 1, date(2026, 10, 19), 3)
    log3 = service.set_note(db, 1, date(2026, 10, 19), "第四天")
    assert (log3.note, log3.pain_level, log3.period_id) == ("第四天", 3, record.id)

    # 历史遗留的非经期疼痛，在写 note 时被清空
    db.add(PeriodLog(user_id=1, log_date=date(2026, 10, 28), pain_level=2))
    db.commit()
    log4 = service.set_note(db, 1, date(2026, 10, 28), "写记事")
    assert (log4.note, log4.pain_level, log4.period_id) == ("写记事", None, None)


def test_calendar_returns_note_and_null_pain(db):
    service.create_period(db, 1, ANCHOR, date(2026, 10, 20))
    service.set_note(db, 1, ANCHOR, "经期第一天")
    service.set_note(db, 1, date(2026, 10, 29), "排卵日记录")
    october = _cal(db, 2026, 10)

    assert october["2026-10-16"]["note"] == "经期第一天"
    assert october["2026-10-16"]["pain_level"] is None
    assert october["2026-10-16"]["pain_recorded"] is False
    assert october["2026-10-29"]["note"] == "排卵日记录"


def test_list_logs_only_content_and_paginated(db):
    record = service.create_period(db, 1, ANCHOR, date(2026, 10, 20))
    service.set_pain(db, 1, date(2026, 10, 17), 2)
    service.set_note(db, 1, date(2026, 10, 29), "排卵日记录")
    service.set_note(db, 1, date(2026, 10, 30), "")  # 空 note 不产生有效列表行

    res = service.list_logs(db, 1, page=1, page_size=1)
    assert (res["total"], res["pages"], res["page_size"]) == (2, 2, 1)
    assert res["list"][0] == {
        "id": res["list"][0]["id"],
        "date": "2026-10-29",
        "pain_level": None,
        "note": "排卵日记录",
        "period_id": None,
    }

    second = service.list_logs(db, 1, page=2, page_size=1)["list"]
    assert len(second) == 1
    assert second[0]["date"] == "2026-10-17"
    assert second[0]["pain_level"] == 2
    assert second[0]["period_id"] == record.id


# ---------- 激素文案 ----------
def test_hormone_copy_contract():
    """每阶段两份、70 字以内、两句话各占一行。"""
    for variants in PHASE_HORMONE.values():
        assert len(variants) == 2
        for text in variants:
            assert len(text) <= 70
            assert text.count("\n") == 1


def test_hormone_text_splits_phase_by_half(db):
    service.create_period(db, 1, ANCHOR, date(2026, 10, 20))  # 28 天段，经期 5 天
    october = _cal(db, 2026, 10)
    november = _cal(db, 2026, 11)

    # 经期 5 天：前 2 天 a、后 3 天 b
    menstrual_a, menstrual_b = PHASE_HORMONE[PHASE_MENSTRUAL]
    assert october["2026-10-16"]["hormone_text"] == menstrual_a
    assert october["2026-10-17"]["hormone_text"] == menstrual_a
    assert october["2026-10-18"]["hormone_text"] == menstrual_b
    assert october["2026-10-20"]["hormone_text"] == menstrual_b

    # 卵泡期 8 天：前 4 天后 4 天
    follicular_a, follicular_b = PHASE_HORMONE[PHASE_FOLLICULAR_PRE]
    assert october["2026-10-21"]["hormone_text"] == follicular_a
    assert october["2026-10-24"]["hormone_text"] == follicular_a
    assert october["2026-10-25"]["hormone_text"] == follicular_b
    assert october["2026-10-28"]["hormone_text"] == follicular_b

    # 排卵日 1 天：用 a
    assert october["2026-10-29"]["hormone_text"] == PHASE_HORMONE[PHASE_OVULATION_DAY][0]

    # 排卵后期 2 天：1 天 a、1 天 b
    post_a, post_b = PHASE_HORMONE[PHASE_FOLLICULAR_POST]
    assert october["2026-10-30"]["hormone_text"] == post_a
    assert october["2026-10-31"]["hormone_text"] == post_b

    # 黄体中期 4 天：前 2 天后 2 天
    mid_a, mid_b = PHASE_HORMONE[PHASE_LUTEAL_MID]
    assert november["2026-11-05"]["hormone_text"] == mid_a
    assert november["2026-11-06"]["hormone_text"] == mid_a
    assert november["2026-11-07"]["hormone_text"] == mid_b
    assert november["2026-11-08"]["hormone_text"] == mid_b


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
