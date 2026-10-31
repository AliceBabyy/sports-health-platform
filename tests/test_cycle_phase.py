"""生理周期单测（MC-05/10/11）：七阶段边界、疼痛优先级、预测日、取模回卷。"""
from datetime import date, timedelta

from app.core.constants import (
    PHASE_FOLLICULAR_POST,
    PHASE_FOLLICULAR_PRE,
    PHASE_LUTEAL_EARLY,
    PHASE_LUTEAL_LATE,
    PHASE_LUTEAL_MID,
    PHASE_MENSTRUAL,
    PHASE_OVULATION_DAY,
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


def test_sport_level_pain_priority():
    # 疼痛≥2 一律休息（MC-11）
    assert service.sport_level_for(PHASE_OVULATION_DAY, 2) == SPORT_REST
    assert service.sport_level_for(PHASE_MENSTRUAL, 2) == SPORT_REST
    assert service.sport_level_for(PHASE_LUTEAL_EARLY, 3) == SPORT_REST


def test_sport_level_high():
    # 排卵日/排卵期前后且疼痛=0 → 精力旺盛
    assert service.sport_level_for(PHASE_OVULATION_DAY, 0) == SPORT_HIGH
    assert service.sport_level_for(PHASE_FOLLICULAR_PRE, 0) == SPORT_HIGH
    assert service.sport_level_for(PHASE_FOLLICULAR_POST, 0) == SPORT_HIGH


def test_sport_level_good():
    # 排卵期前期/黄体期前中期且疼痛≤1 → 状态良好
    assert service.sport_level_for(PHASE_FOLLICULAR_PRE, 1) == SPORT_GOOD
    assert service.sport_level_for(PHASE_LUTEAL_EARLY, 0) == SPORT_GOOD
    assert service.sport_level_for(PHASE_LUTEAL_MID, 1) == SPORT_GOOD


def test_sport_level_rest_cases():
    # 月经期 → 休息；黄体后期 → 休息；排卵日疼痛=1 → 休息
    assert service.sport_level_for(PHASE_MENSTRUAL, 0) == SPORT_REST
    assert service.sport_level_for(PHASE_LUTEAL_LATE, 0) == SPORT_REST
    assert service.sport_level_for(PHASE_LUTEAL_LATE, 1) == SPORT_REST
    assert service.sport_level_for(PHASE_OVULATION_DAY, 1) == SPORT_REST


def test_next_period_prediction(db):
    service.create_period(db, 1, ANCHOR, None, None, None)
    assert service.next_period_date(db, 1) == ANCHOR + timedelta(days=CL)


def test_calendar_month_phase_and_pain(db):
    service.create_period(db, 1, ANCHOR, None, None, None)
    service.set_pain(db, 1, ANCHOR + timedelta(days=13), 3)  # 排卵日疼痛3 → 休息
    cal = service.calendar_month(db, 1, 2026, 10)
    by_date = {d["date"]: d for d in cal["days"]}
    assert by_date["2026-10-29"]["phase_key"] == PHASE_OVULATION_DAY
    assert by_date["2026-10-29"]["sport_level"] == SPORT_REST  # 疼痛≥2 最高优先
    assert by_date["2026-10-29"]["pain_level"] == 3
    assert by_date["2026-10-16"]["is_period"] is True
    assert cal["overview"]["next_period"] == (ANCHOR + timedelta(days=CL)).isoformat()
