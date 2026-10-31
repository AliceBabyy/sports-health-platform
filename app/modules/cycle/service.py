"""生理周期 service：七阶段推算、三档运动判定、月历、预测日、设置与疼痛（MC-01~13）。

推算基线（需求 7.2/9.3 定稿）：
- 锚点 = 最近一次月经开始日；无记录时以「今天」为默认锚点（按默认周期回推）。
- N = (day - anchor).days + 1；N_eff = ((N-1) % cycle_length) + 1 做循环取模。
- 排卵日 = 周期长度 - 14；七阶段独立枚举，禁止合并。
- 运动等级（MC-10/11）：疼痛≥2 一律 rest；排卵日/排卵期前后且疼痛=0 → high；
  排卵期前期/黄体期前中期且疼痛≤1 → good；其余 rest。
"""
from datetime import date, timedelta

import calendar as _calendar
from sqlalchemy.orm import Session

from app.core.constants import (
    DEFAULT_CYCLE_LENGTH,
    DEFAULT_PERIOD_LENGTH,
    GOOD_LEVEL_PHASES,
    HIGH_LEVEL_PHASES,
    OVULATION_OFFSET,
    PHASE_FOLLICULAR_POST,
    PHASE_FOLLICULAR_PRE,
    PHASE_LUTEAL_EARLY,
    PHASE_LUTEAL_LATE,
    PHASE_LUTEAL_MID,
    PHASE_MENSTRUAL,
    PHASE_OVULATION_DAY,
    PHASE_LABELS,
    SPORT_GOOD,
    SPORT_HIGH,
    SPORT_LABELS,
    SPORT_REST,
    today_local,
)
from app.modules.cycle.models import CycleSetting, DailyPainLog, PeriodRecord



# ---------- 设置 ----------
def get_settings(db: Session, user_id: int) -> CycleSetting:
    setting = db.get(CycleSetting, user_id)
    if setting is None:
        setting = CycleSetting(user_id=user_id, cycle_length=DEFAULT_CYCLE_LENGTH, period_length=DEFAULT_PERIOD_LENGTH)
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


def update_settings(db: Session, user_id: int, cycle_length: int, period_length: int) -> CycleSetting:
    setting = get_settings(db, user_id)
    setting.cycle_length = cycle_length
    setting.period_length = period_length
    db.commit()
    db.refresh(setting)
    return setting


# ---------- 月经记录 ----------
def list_periods(db: Session, user_id: int) -> list[dict]:
    rows = (
        db.query(PeriodRecord)
        .filter(PeriodRecord.user_id == user_id)
        .order_by(PeriodRecord.start_date.desc())
        .all()
    )
    return [
        {"id": r.id, "start_date": r.start_date.isoformat(), "end_date": r.end_date.isoformat() if r.end_date else None}
        for r in rows
    ]


def get_anchor_date(db: Session, user_id: int) -> date:
    """推算锚点：最近一次月经开始日；无记录 → 今天。"""
    row = (
        db.query(PeriodRecord)
        .filter(PeriodRecord.user_id == user_id)
        .order_by(PeriodRecord.start_date.desc())
        .first()
    )
    return row.start_date if row else today_local()


def next_period_date(db: Session, user_id: int) -> date:
    """MC-05：上次月经首日 + 周期长度；无记录时以今天为新周期起点推算。"""
    setting = get_settings(db, user_id)
    anchor = get_anchor_date(db, user_id)
    return anchor + timedelta(days=setting.cycle_length)


def create_period(db: Session, user_id: int, start_date: date, end_date: date | None, cycle_length: int | None, period_length: int | None):
    """MC-02：记录月经开始（可补结束日）；可选同步更新周期/经期长度。"""
    row = PeriodRecord(user_id=user_id, start_date=start_date, end_date=end_date)
    db.add(row)
    if cycle_length is not None or period_length is not None:
        setting = get_settings(db, user_id)
        if cycle_length is not None:
            setting.cycle_length = cycle_length
        if period_length is not None:
            setting.period_length = period_length
    db.commit()
    db.refresh(row)
    return row


def update_period(db: Session, user_id: int, record_id: int, start_date: date | None, end_date: date | None) -> PeriodRecord | None:
    row = db.query(PeriodRecord).filter(PeriodRecord.id == record_id, PeriodRecord.user_id == user_id).first()
    if row is None:
        return None
    if start_date is not None:
        row.start_date = start_date
    if end_date is not None:
        row.end_date = end_date
    db.commit()
    db.refresh(row)
    return row


def delete_period(db: Session, user_id: int, record_id: int) -> bool:
    row = db.query(PeriodRecord).filter(PeriodRecord.id == record_id, PeriodRecord.user_id == user_id).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


# ---------- 疼痛 ----------
def set_pain(db: Session, user_id: int, log_date: date, pain_level: int) -> DailyPainLog:
    """MC-03：写入每日疼痛，重写覆盖旧值。"""
    row = (
        db.query(DailyPainLog)
        .filter(DailyPainLog.user_id == user_id, DailyPainLog.log_date == log_date)
        .first()
    )
    if row is None:
        row = DailyPainLog(user_id=user_id, log_date=log_date, pain_level=pain_level)
        db.add(row)
    else:
        row.pain_level = pain_level
    db.commit()
    db.refresh(row)
    return row


# ---------- 推算（纯函数，可单测） ----------
def cycle_day_number(day: date, anchor: date) -> int:
    """N（锚点日=1）。"""
    return (day - anchor).days + 1


def effective_day_number(day: date, anchor: date, cycle_length: int) -> int:
    """N_eff：循环取模到 1..cycle_length，负数日期也可正确回卷。"""
    n = cycle_day_number(day, anchor)
    return ((n - 1) % cycle_length) + 1


def phase_for(day: date, anchor: date, cycle_length: int, period_length: int) -> str:
    """七阶段推算（独立枚举，禁止合并）。"""
    ovulation_day = min(max(cycle_length - OVULATION_OFFSET, period_length + 1), cycle_length)
    n = effective_day_number(day, anchor, cycle_length)
    if n <= period_length:
        return PHASE_MENSTRUAL
    if n < ovulation_day:
        return PHASE_FOLLICULAR_PRE
    if n == ovulation_day:
        return PHASE_OVULATION_DAY
    if n <= ovulation_day + 2:
        return PHASE_FOLLICULAR_POST
    if n <= ovulation_day + 6:
        return PHASE_LUTEAL_EARLY
    if n <= ovulation_day + 10:
        return PHASE_LUTEAL_MID
    return PHASE_LUTEAL_LATE


def sport_level_for(phase_key: str, pain_level: int) -> str:
    """三档运动等级（MC-10/11）：疼痛≥2 优先级最高。"""
    if pain_level >= 2:
        return SPORT_REST
    if phase_key in HIGH_LEVEL_PHASES and pain_level == 0:
        return SPORT_HIGH
    if phase_key in GOOD_LEVEL_PHASES and pain_level <= 1:
        return SPORT_GOOD
    return SPORT_REST


def ovulation_date_for(anchor: date, cycle_length: int, period_length: int) -> date:
    ovulation_day = min(max(cycle_length - OVULATION_OFFSET, period_length + 1), cycle_length)
    return anchor + timedelta(days=ovulation_day - 1)


# ---------- 月历 ----------
def calendar_month(db: Session, user_id: int, year: int, month: int) -> dict:
    """逐日 {date, phase_key, phase_label, sport_level, sport_label, is_period, pain_level}。"""
    setting = get_settings(db, user_id)
    anchor = get_anchor_date(db, user_id)
    _, last_day = _calendar.monthrange(year, month)
    pain_rows = (
        db.query(DailyPainLog)
        .filter(DailyPainLog.user_id == user_id, DailyPainLog.log_date >= date(year, month, 1), DailyPainLog.log_date <= date(year, month, last_day))
        .all()
    )
    pain_map = {r.log_date: r.pain_level for r in pain_rows}

    days = []
    for day in range(1, last_day + 1):
        d = date(year, month, day)
        pain = pain_map.get(d, 0)
        if d < anchor:
            # 推算锚点（最近月经首日）之前的日期无阶段，不显示推算结果（无记录锚点=今天同理）
            days.append(
                {
                    "date": d.isoformat(),
                    "phase_key": None,
                    "phase_label": None,
                    "sport_level": None,
                    "sport_label": None,
                    "is_period": False,
                    "pain_level": pain,
                }
            )
            continue
        phase = phase_for(d, anchor, setting.cycle_length, setting.period_length)
        level = sport_level_for(phase, pain)
        days.append(
            {
                "date": d.isoformat(),
                "phase_key": phase,
                "phase_label": PHASE_LABELS[phase],
                "sport_level": level,
                "sport_label": SPORT_LABELS[level],
                "is_period": phase == PHASE_MENSTRUAL,
                "pain_level": pain,
            }
        )

    ovulation_day = min(max(setting.cycle_length - OVULATION_OFFSET, setting.period_length + 1), setting.cycle_length)
    today = today_local()
    today_phase = phase_for(today, anchor, setting.cycle_length, setting.period_length)
    today_level = sport_level_for(today_phase, _today_pain(db, user_id, today, pain_map))
    return {
        "year": year,
        "month": month,
        "days": days,
        "overview": {
            "anchor": anchor.isoformat(),
            "cycle_length": setting.cycle_length,
            "period_length": setting.period_length,
            "ovulation_date": (anchor + timedelta(days=ovulation_day - 1)).isoformat(),
            "next_period": next_period_date(db, user_id).isoformat(),
            "period_start": anchor.isoformat(),
            "period_end": (anchor + timedelta(days=setting.period_length - 1)).isoformat(),
            "cycle_day_today": effective_day_number(today, anchor, setting.cycle_length),
            "progress": f"{effective_day_number(today, anchor, setting.cycle_length)}/{setting.cycle_length}",
        },
        "today": {
            "date": today.isoformat(),
            "phase_key": today_phase,
            "phase_label": PHASE_LABELS[today_phase],
            "sport_level": today_level,
            "sport_label": SPORT_LABELS[today_level],
        },
    }


def _today_pain(db: Session, user_id: int, today: date, pain_map: dict) -> int:
    if today in pain_map:
        return pain_map[today]
    row = db.query(DailyPainLog).filter(DailyPainLog.user_id == user_id, DailyPainLog.log_date == today).first()
    return row.pain_level if row else 0


# ---------- 侧边栏今日摘要 ----------
def get_today_summary(user_id: int) -> dict:
    """页面侧边栏“今天”小卡信息。"""
    from database import SessionLocal

    db = SessionLocal()
    try:
        setting = get_settings(db, user_id)
        anchor = get_anchor_date(db, user_id)
        today = today_local()
        phase = phase_for(today, anchor, setting.cycle_length, setting.period_length)
        row = db.query(DailyPainLog).filter(DailyPainLog.user_id == user_id, DailyPainLog.log_date == today).first()
        pain = row.pain_level if row else 0
        level = sport_level_for(phase, pain)
        return {
            "cycle_day": effective_day_number(today, anchor, setting.cycle_length),
            "phase_key": phase,
            "phase_label": PHASE_LABELS[phase],
            "sport_level": level,
            "sport_label": SPORT_LABELS[level],
        }
    finally:
        db.close()
