"""生理周期 service：七阶段推算、四档运动判定、月历、预测日、设置与疼痛（MC-01~13）。

推算基线（需求 7.2/9.3 定稿）：
- 锚点 = 最近一次月经开始日；无记录时以「今天」为默认锚点（按默认周期回推）。
- N = (day - anchor).days + 1；N_eff = ((N-1) % cycle_length) + 1 做循环取模。
- 排卵日 = 周期长度 - 14；七阶段独立枚举，禁止合并。
- 运动等级（MC-10/11）：按阶段内日序细分四档；疼痛≥2 优先覆盖为 rest。
"""
from datetime import date, timedelta

import calendar as _calendar
from sqlalchemy.orm import Session

from app.core.constants import (
    DEFAULT_CYCLE_LENGTH,
    DEFAULT_PERIOD_LENGTH,
    OVULATION_OFFSET,
    PHASE_FOLLICULAR_POST,
    PHASE_FOLLICULAR_PRE,
    PHASE_LUTEAL_EARLY,
    PHASE_LUTEAL_LATE,
    PHASE_LUTEAL_MID,
    PHASE_MENSTRUAL,
    PHASE_OVULATION_DAY,
    PHASE_LABELS,
    PERIOD_STATE_LABELS,
    PERIOD_STATE_PREDICTED,
    PERIOD_STATE_RECORDED,
    SPORT_AVERAGE,
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


def get_anchor_date(db: Session, user_id: int, as_of: date | None = None) -> date:
    """取指定日期之前最近的月经首日；无记录时以今天为默认锚点。"""
    as_of = as_of or today_local()
    row = (
        db.query(PeriodRecord)
        .filter(PeriodRecord.user_id == user_id, PeriodRecord.start_date <= as_of)
        .order_by(PeriodRecord.start_date.desc())
        .first()
    )
    return row.start_date if row else today_local()


def next_period_date(db: Session, user_id: int) -> date:
    """MC-05：从最近有效锚点滚动预测今天之后的下一次月经。"""
    setting = get_settings(db, user_id)
    anchor = get_anchor_date(db, user_id)
    today = today_local()
    cycles = max(1, (today - anchor).days // setting.cycle_length + 1)
    return anchor + timedelta(days=cycles * setting.cycle_length)


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


def update_period(db: Session, user_id: int, record_id: int, start_date: date | None, end_date: date | None, update_end: bool = False) -> PeriodRecord | None:
    row = db.query(PeriodRecord).filter(PeriodRecord.id == record_id, PeriodRecord.user_id == user_id).first()
    if row is None:
        return None
    if start_date is not None:
        row.start_date = start_date
    if update_end:
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


def sport_level_for(phase_key: str, cycle_day: int, cycle_length: int, period_length: int, pain_level: int) -> str:
    """按阶段内日序判定四档；中重度疼痛优先休息。"""
    if pain_level >= 2:
        return SPORT_REST
    if phase_key == PHASE_MENSTRUAL:
        if cycle_day <= 3:
            return SPORT_REST
        return SPORT_AVERAGE if cycle_day == 4 else SPORT_GOOD
    if phase_key in (PHASE_FOLLICULAR_PRE, PHASE_OVULATION_DAY, PHASE_FOLLICULAR_POST):
        return SPORT_HIGH
    if phase_key == PHASE_LUTEAL_EARLY:
        return SPORT_GOOD
    ovulation_day = min(max(cycle_length - OVULATION_OFFSET, period_length + 1), cycle_length)
    if phase_key == PHASE_LUTEAL_MID:
        return SPORT_GOOD if cycle_day <= ovulation_day + 8 else SPORT_AVERAGE
    if phase_key == PHASE_LUTEAL_LATE:
        return SPORT_AVERAGE if cycle_day <= ovulation_day + 12 else SPORT_REST
    return SPORT_REST


def ovulation_date_for(anchor: date, cycle_length: int, period_length: int) -> date:
    ovulation_day = min(max(cycle_length - OVULATION_OFFSET, period_length + 1), cycle_length)
    return anchor + timedelta(days=ovulation_day - 1)


def period_windows(period_rows: list, period_length: int) -> list[tuple[date, date]]:
    """把月经记录展开成「已记录经期」窗口。

    有结束日按记录结束日；无结束日按当前经期长度从首日推导（与阶段推算窗口一致）。
    """
    windows = []
    for row in period_rows:
        start = row.start_date
        end = row.end_date if row.end_date and row.end_date >= start else start + timedelta(days=max(period_length, 1) - 1)
        windows.append((start, end))
    return windows


def period_state_for(day: date, phase_key: str | None, windows: list[tuple[date, date]], as_of: date | None = None) -> str | None:
    """经期状态：真实记录覆盖 → recorded；当日及以后由推算得出 → predicted；非经期 → None。

    as_of 为「今天」：早于今天且未被记录覆盖的经期日不算预测，仍按推算阶段展示。
    """
    if phase_key != PHASE_MENSTRUAL:
        return None
    for start, end in windows:
        if start <= day <= end:
            return PERIOD_STATE_RECORDED
    if as_of is not None and day < as_of:
        return None
    return PERIOD_STATE_PREDICTED


# ---------- 月历 ----------
def calendar_month(db: Session, user_id: int, year: int, month: int) -> dict:
    """逐日 {date, phase_key, phase_label, sport_level, sport_label, is_period, period_state,
    period_label, pain_level}。

    period_state 标注口径：落在真实月经记录窗口内为 recorded（经期）；
    今天及以后由推算得出的经期为 predicted（预测经期）。
    """
    setting = get_settings(db, user_id)
    today = today_local()
    anchor = get_anchor_date(db, user_id, today)
    _, last_day = _calendar.monthrange(year, month)
    period_rows = (
        db.query(PeriodRecord)
        .filter(PeriodRecord.user_id == user_id, PeriodRecord.start_date <= date(year, month, last_day))
        .order_by(PeriodRecord.start_date.asc())
        .all()
    )
    period_starts = {row.start_date for row in period_rows}
    windows = period_windows(period_rows, setting.period_length)
    pain_rows = (
        db.query(DailyPainLog)
        .filter(DailyPainLog.user_id == user_id, DailyPainLog.log_date >= date(year, month, 1), DailyPainLog.log_date <= date(year, month, last_day))
        .all()
    )
    pain_map = {r.log_date: r.pain_level for r in pain_rows}

    days = []
    record_index = 0
    day_anchor = None
    for day in range(1, last_day + 1):
        d = date(year, month, day)
        while record_index < len(period_rows) and period_rows[record_index].start_date <= d:
            day_anchor = period_rows[record_index].start_date
            record_index += 1
        pain = pain_map.get(d, 0)
        effective_anchor = day_anchor or (today if not period_rows else None)
        if effective_anchor is None or d < effective_anchor:
            days.append(
                {
                    "date": d.isoformat(),
                    "phase_key": None,
                    "phase_label": None,
                    "sport_level": None,
                    "sport_label": None,
                    "is_period": False,
                    "period_state": None,
                    "period_label": None,
                    "pain_level": pain,
                    "pain_recorded": d in pain_map,
                    "is_recorded_start": d in period_starts,
                    "cycle_day": None,
                }
            )
            continue
        phase = phase_for(d, effective_anchor, setting.cycle_length, setting.period_length)
        cycle_day = effective_day_number(d, effective_anchor, setting.cycle_length)
        level = sport_level_for(phase, cycle_day, setting.cycle_length, setting.period_length, pain)
        period_state = period_state_for(d, phase, windows, today)
        days.append(
            {
                "date": d.isoformat(),
                "phase_key": phase,
                "phase_label": PHASE_LABELS[phase],
                "sport_level": level,
                "sport_label": SPORT_LABELS[level],
                "is_period": phase == PHASE_MENSTRUAL,
                "period_state": period_state,
                "period_label": PERIOD_STATE_LABELS[period_state] if period_state else None,
                "pain_level": pain,
                "pain_recorded": d in pain_map,
                "is_recorded_start": d in period_starts,
                "cycle_day": cycle_day,
            }
        )

    ovulation_day = min(max(setting.cycle_length - OVULATION_OFFSET, setting.period_length + 1), setting.cycle_length)
    today_phase = phase_for(today, anchor, setting.cycle_length, setting.period_length)
    today_cycle_day = effective_day_number(today, anchor, setting.cycle_length)
    today_level = sport_level_for(today_phase, today_cycle_day, setting.cycle_length, setting.period_length, _today_pain(db, user_id, today, pain_map))
    current_start = anchor + timedelta(days=((today - anchor).days // setting.cycle_length) * setting.cycle_length)
    return {
        "year": year,
        "month": month,
        "days": days,
        "overview": {
            "anchor": anchor.isoformat(),
            "cycle_length": setting.cycle_length,
            "period_length": setting.period_length,
            "ovulation_date": (current_start + timedelta(days=ovulation_day - 1)).isoformat(),
            "next_period": next_period_date(db, user_id).isoformat(),
            "period_start": current_start.isoformat(),
            "period_end": (current_start + timedelta(days=setting.period_length - 1)).isoformat(),
            "has_records": bool(db.query(PeriodRecord.id).filter(PeriodRecord.user_id == user_id).first()),
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
        cycle_day = effective_day_number(today, anchor, setting.cycle_length)
        level = sport_level_for(phase, cycle_day, setting.cycle_length, setting.period_length, pain)
        return {
            "has_records": bool(db.query(PeriodRecord.id).filter(PeriodRecord.user_id == user_id, PeriodRecord.start_date <= today).first()),
            "cycle_day": cycle_day,
            "phase_key": phase,
            "phase_label": PHASE_LABELS[phase],
            "sport_level": level,
            "sport_label": SPORT_LABELS[level],
        }
    finally:
        db.close()


def build_cycle_link(user, sport: str = "training") -> dict | None:
    """三模块（健身/游泳/舞蹈）页面「周期联动」卡片统一数据来源。

    男性账号或无周期数据时返回 None，页面不渲染卡片。
    返回字段：phase_label / sport_label / sport_level / advice / chips。
    sport：training=健身、swim=游泳、dance=舞蹈，用于差异化建议文案。
    """
    from app.core.constants import PHASE_INFO

    if user.gender == "男":
        return None
    cyc = get_today_summary(user.id)
    if not cyc["has_records"]:
        return None
    info = PHASE_INFO.get(cyc.get("phase_key", ""), {})
    level = cyc.get("sport_level", SPORT_REST)
    chips = {
        SPORT_HIGH: {
            "training": ["建议负荷 +5%", "可冲击 PR"],
            "swim": ["建议距离 +5%", "可冲配速 PR"],
            "dance": ["建议强度 +5%", "可扣难度动作"],
        }.get(sport, []),
        SPORT_GOOD: {
            "training": ["维持常规负荷", "注意补水"],
            "swim": ["维持常规距离", "注意补水"],
            "dance": ["维持常规强度", "注意热身"],
        }.get(sport, []),
        SPORT_AVERAGE: {
            "training": ["适度调整负荷", "关注身体感受"],
            "swim": ["保持舒适配速", "关注身体感受"],
            "dance": ["适度调整强度", "关注身体感受"],
        }.get(sport, []),
        SPORT_REST: {
            "training": ["以拉伸 / 有氧为主", "保证睡眠"],
            "swim": ["以放松游 / 技术为主", "保证睡眠"],
            "dance": ["以拉伸 / 基本功为主", "保证睡眠"],
        }.get(sport, []),
    }[level]
    return {
        "phase_label": cyc.get("phase_label", "—"),
        "sport_label": cyc.get("sport_label", "—"),
        "sport_level": level,
        "advice": info.get("advice", ""),
        "chips": chips,
    }
