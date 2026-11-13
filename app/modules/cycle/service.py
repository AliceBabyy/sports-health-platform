"""生理周期 service：按记录分段推算七阶段、四档运动判定、月历、预测与参考值设置。

口径（2026-11-12 定稿）：
- 事实源只有 period_records 的起止日；经期长度 / 周期长度全部派生，不落库。
- 相邻两条记录划成一段：
    实际间隔在 [技术下限, 45] 天 → 真实段，段长 = 实际间隔；
    实际间隔 46~90 天 → 判为漏记，按参考周期等分成若干有效段（补推段）；
    实际间隔 > 90 天 → 不推算，两段之间留白。
- 段内阶段：经期 1~P；排卵日 = 段长 - 14（黄体固定 14 天，锚定下一次月经首日）；
  排卵后 1~2 / 3~6 / 7~10 / 11~14 天依次为排卵期后期 / 黄体前 / 中 / 后期。
- 只向未来延伸「最新记录后的当前段 + 一个预测段」，超过逾期宽限则不给预测段。
- cycle_settings 仅作参考值：当前段、预测段、补推段使用；真实段不参与。
"""
import calendar as _calendar
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core.constants import (
    DEFAULT_CYCLE_LENGTH,
    DEFAULT_PERIOD_LENGTH,
    GAP_INFER_MAX_DAYS,
    LUTEAL_EARLY_END,
    LUTEAL_MID_END,
    MAX_SEGMENT_DAYS,
    MIN_SEGMENT_DAYS,
    OVULATION_OFFSET,
    OVULATION_POST_POST,
    PERIOD_STATE_INFERRED,
    PERIOD_STATE_LABELS,
    PERIOD_STATE_PREDICTED,
    PERIOD_STATE_RECORDED,
    PHASE_FOLLICULAR_POST,
    PHASE_FOLLICULAR_PRE,
    PHASE_LABELS,
    PHASE_LUTEAL_EARLY,
    PHASE_LUTEAL_LATE,
    PHASE_LUTEAL_MID,
    PHASE_MENSTRUAL,
    PHASE_OVULATION_DAY,
    PREDICT_GRACE_DAYS,
    REFERENCE_PERIOD_MAX,
    SEGMENT_CURRENT,
    SEGMENT_INFERRED,
    SEGMENT_PREDICTED,
    SEGMENT_RECORDED,
    SPORT_AVERAGE,
    SPORT_GOOD,
    SPORT_HIGH,
    SPORT_LABELS,
    SPORT_REST,
    today_local,
)
from app.core.exceptions import AppError
from app.modules.cycle.models import CycleSetting, DailyPainLog, PeriodRecord


@dataclass(frozen=True)
class Segment:
    """一段周期：起点、段长、经期天数、来源、是否可推算阶段。"""

    start: date
    length: int
    period_length: int
    source: str
    inferable: bool = True

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.length - 1)


# ---------- 设置（仅参考值） ----------
def get_settings(db: Session, user_id: int) -> CycleSetting:
    setting = db.get(CycleSetting, user_id)
    if setting is None:
        setting = CycleSetting(user_id=user_id, cycle_length=DEFAULT_CYCLE_LENGTH, period_length=DEFAULT_PERIOD_LENGTH)
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


def update_settings(db: Session, user_id: int, cycle_length: int, period_length: int) -> CycleSetting:
    """参考值只由页面「周期参数」写入，记录月经不会改动它。"""
    setting = get_settings(db, user_id)
    setting.cycle_length = cycle_length
    setting.period_length = period_length
    db.commit()
    db.refresh(setting)
    return setting


# ---------- 月经记录 ----------
def list_periods(db: Session, user_id: int) -> list[dict]:
    """记录列表：经期长度 / 周期长度均由记录实时派生，算不出时为 null（前端回退参考值）。"""
    rows = (
        db.query(PeriodRecord)
        .filter(PeriodRecord.user_id == user_id)
        .order_by(PeriodRecord.start_date.asc())
        .all()
    )
    result = []
    for idx, row in enumerate(rows):
        period_length = (
            (row.end_date - row.start_date).days + 1
            if row.end_date and row.end_date >= row.start_date
            else None
        )
        cycle_length = None
        if idx + 1 < len(rows):
            gap = (rows[idx + 1].start_date - row.start_date).days
            if gap <= MAX_SEGMENT_DAYS:
                cycle_length = gap
        result.append(
            {
                "id": row.id,
                "start_date": row.start_date.isoformat(),
                "end_date": row.end_date.isoformat() if row.end_date else None,
                "period_length": period_length,
                "cycle_length": cycle_length,
            }
        )
    result.reverse()
    return result


def _tech_min(period_length: int) -> int:
    """段长技术下限：保证排卵日（段长 - 14）不落进经期。"""
    return max(MIN_SEGMENT_DAYS, period_length + OVULATION_OFFSET + 1)


def _period_length_of(row: PeriodRecord, ref_period: int) -> int:
    if row.end_date and row.end_date >= row.start_date:
        return (row.end_date - row.start_date).days + 1
    return ref_period


def _current_length(period_length: int, ref_cycle: int) -> int:
    """当前段（最新记录之后）的段长：参考周期，且保证能推出排卵日。"""
    return max(ref_cycle, period_length + OVULATION_OFFSET + 1)


def _split_gap(gap: int, ref_cycle: int, period_length: int) -> list[int] | None:
    """把漏记间隔等分成 k 段，每段落在 [技术下限, 45] 且最接近参考周期；无解返回 None。"""
    lo = _tech_min(period_length)
    best: tuple[float, int] | None = None
    for k in range(2, gap // lo + 1):
        avg = gap / k
        if not lo <= avg <= MAX_SEGMENT_DAYS:
            continue
        score = abs(avg - ref_cycle)
        if best is None or score < best[0]:
            best = (score, k)
    if best is None:
        return None
    k = best[1]
    base, rem = divmod(gap, k)
    return [base + 1 if i < rem else base for i in range(k)]


def build_segments(db: Session, user_id: int, setting: CycleSetting | None = None, today: date | None = None) -> list[Segment]:
    """按月记录构建连续段：真实段 / 补推段 / 当前段 / 预测段。"""
    setting = setting or get_settings(db, user_id)
    today = today or today_local()
    rows = (
        db.query(PeriodRecord)
        .filter(PeriodRecord.user_id == user_id)
        .order_by(PeriodRecord.start_date.asc())
        .all()
    )
    if not rows:
        return []

    ref_cycle = setting.cycle_length
    ref_period = setting.period_length
    segments: list[Segment] = []

    for idx, row in enumerate(rows):
        period_length = _period_length_of(row, ref_period)

        if idx + 1 >= len(rows):
            segments.append(Segment(row.start_date, _current_length(period_length, ref_cycle), period_length, SEGMENT_CURRENT))
            pred_start = row.start_date + timedelta(days=_current_length(period_length, ref_cycle))
            if today <= pred_start + timedelta(days=PREDICT_GRACE_DAYS):
                segments.append(Segment(pred_start, max(ref_cycle, ref_period + OVULATION_OFFSET + 1), ref_period, SEGMENT_PREDICTED))
            break

        gap = (rows[idx + 1].start_date - row.start_date).days
        if gap > GAP_INFER_MAX_DAYS:
            continue  # 超过 3 个月：不补推，留白
        if gap > MAX_SEGMENT_DAYS:
            parts = _split_gap(gap, ref_cycle, period_length)
            if parts is None:
                continue
            start = row.start_date
            for part_idx, length in enumerate(parts):
                segments.append(
                    Segment(start, length, period_length if part_idx == 0 else ref_period, SEGMENT_INFERRED)
                )
                start += timedelta(days=length)
            continue

        segments.append(
            Segment(row.start_date, gap, period_length, SEGMENT_RECORDED, inferable=gap >= _tech_min(period_length))
        )

    return segments


def segment_for_day(segments: list[Segment], day: date) -> Segment | None:
    for seg in segments:
        if seg.start <= day <= seg.end:
            return seg
    return None


def phase_in_segment(day: date, seg: Segment) -> str | None:
    """段内七阶段：排卵日 = 段长 - 14，经期按该段经期天数。"""
    offset = (day - seg.start).days + 1
    if offset < 1 or offset > seg.length:
        return None
    if not seg.inferable:
        return PHASE_MENSTRUAL if offset <= min(seg.period_length, seg.length) else None

    ovulation_day = seg.length - OVULATION_OFFSET
    if offset <= seg.period_length:
        return PHASE_MENSTRUAL
    if offset < ovulation_day:
        return PHASE_FOLLICULAR_PRE
    if offset == ovulation_day:
        return PHASE_OVULATION_DAY
    if offset <= ovulation_day + OVULATION_POST_POST:
        return PHASE_FOLLICULAR_POST
    if offset <= ovulation_day + LUTEAL_EARLY_END:
        return PHASE_LUTEAL_EARLY
    if offset <= ovulation_day + LUTEAL_MID_END:
        return PHASE_LUTEAL_MID
    return PHASE_LUTEAL_LATE


def sport_level_for(phase_key: str, cycle_day: int, segment_length: int, period_length: int, pain_level: int) -> str:
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
    ovulation_day = segment_length - OVULATION_OFFSET
    if phase_key == PHASE_LUTEAL_MID:
        return SPORT_GOOD if cycle_day <= ovulation_day + 8 else SPORT_AVERAGE
    if phase_key == PHASE_LUTEAL_LATE:
        return SPORT_AVERAGE if cycle_day <= ovulation_day + 12 else SPORT_REST
    return SPORT_REST


def _record_windows(rows: list[PeriodRecord], ref_period: int) -> list[tuple[date, date]]:
    """真实记录窗口：有结束日按结束日，无结束日按参考经期天数从首日推导。"""
    windows = []
    for row in rows:
        start = row.start_date
        end = row.end_date if row.end_date and row.end_date >= start else start + timedelta(days=ref_period - 1)
        windows.append((start, end))
    return windows


def _period_state(day: date, phase: str | None, seg: Segment | None, windows: list[tuple[date, date]]) -> str | None:
    for start, end in windows:
        if start <= day <= end:
            return PERIOD_STATE_RECORDED
    if phase == PHASE_MENSTRUAL and seg is not None:
        if seg.source == SEGMENT_INFERRED:
            return PERIOD_STATE_INFERRED
        if seg.source == SEGMENT_PREDICTED:
            return PERIOD_STATE_PREDICTED
    return None


# ---------- 预测 ----------
def next_period_date(db: Session, user_id: int, setting: CycleSetting | None = None) -> date | None:
    """只预测最新一次记录之后的下一段起点；无记录时返回 None。"""
    setting = setting or get_settings(db, user_id)
    row = (
        db.query(PeriodRecord)
        .filter(PeriodRecord.user_id == user_id)
        .order_by(PeriodRecord.start_date.desc())
        .first()
    )
    if row is None:
        return None
    period_length = _period_length_of(row, setting.period_length)
    return row.start_date + timedelta(days=_current_length(period_length, setting.cycle_length))


# ---------- 月经记录写入 ----------
def validate_period_bounds(db: Session, user_id: int, start_date: date, end_date: date | None, exclude_id: int | None = None) -> None:
    """相邻首日间隔下限校验、结束日上限校验；只拦会影响阶段推断的情况。"""
    today = today_local()
    if end_date is not None:
        if end_date < start_date:
            raise AppError(422, "结束日期不能早于开始日期")
        if end_date > today:
            raise AppError(422, "结束日期不能晚于今天")
        if (end_date - start_date).days + 1 > REFERENCE_PERIOD_MAX:
            raise AppError(422, f"经期天数不能超过 {REFERENCE_PERIOD_MAX} 天")

    setting = get_settings(db, user_id)
    query = db.query(PeriodRecord).filter(PeriodRecord.user_id == user_id)
    if exclude_id is not None:
        query = query.filter(PeriodRecord.id != exclude_id)
    prev = query.filter(PeriodRecord.start_date < start_date).order_by(PeriodRecord.start_date.desc()).first()
    nxt = query.filter(PeriodRecord.start_date > start_date).order_by(PeriodRecord.start_date.asc()).first()
    new_period_length = (end_date - start_date).days + 1 if end_date else setting.period_length

    if prev is not None:
        gap = (start_date - prev.start_date).days
        if gap < _tech_min(_period_length_of(prev, setting.period_length)):
            raise AppError(
                422,
                f"与上一条记录 {prev.start_date.isoformat()} 仅间隔 {gap} 天，疑似同一次月经，请直接编辑已有记录",
            )
    if nxt is not None:
        gap = (nxt.start_date - start_date).days
        if gap < _tech_min(new_period_length):
            raise AppError(
                422,
                f"与下一条记录 {nxt.start_date.isoformat()} 仅间隔 {gap} 天，疑似同一次月经，请直接编辑已有记录",
            )
        if end_date is not None and end_date >= nxt.start_date:
            raise AppError(422, "结束日期不能晚于下一条记录的开始日期")


def create_period(db: Session, user_id: int, start_date: date, end_date: date | None) -> PeriodRecord:
    row = PeriodRecord(user_id=user_id, start_date=start_date, end_date=end_date)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_period(
    db: Session,
    user_id: int,
    record_id: int,
    start_date: date | None,
    end_date: date | None,
    update_end: bool = False,
) -> PeriodRecord | None:
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


# ---------- 月历 ----------
def calendar_month(db: Session, user_id: int, year: int, month: int) -> dict:
    """逐日阶段 + 三态经期；历史只呈现记录支撑的部分，未来只推一段。"""
    setting = get_settings(db, user_id)
    today = today_local()
    rows = (
        db.query(PeriodRecord)
        .filter(PeriodRecord.user_id == user_id)
        .order_by(PeriodRecord.start_date.asc())
        .all()
    )
    segments = build_segments(db, user_id, setting=setting, today=today)
    windows = _record_windows(rows, setting.period_length)
    recorded_starts = {row.start_date for row in rows}

    _, last_day = _calendar.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end = date(year, month, last_day)
    pain_rows = (
        db.query(DailyPainLog)
        .filter(DailyPainLog.user_id == user_id, DailyPainLog.log_date >= month_start, DailyPainLog.log_date <= month_end)
        .all()
    )
    pain_map = {r.log_date: r.pain_level for r in pain_rows}

    days = []
    for day_num in range(1, last_day + 1):
        d = date(year, month, day_num)
        seg = segment_for_day(segments, d)
        pain = pain_map.get(d, 0)
        phase = phase_in_segment(d, seg) if seg else None
        cycle_day = (d - seg.start).days + 1 if seg else None
        level = sport_level_for(phase, cycle_day, seg.length, seg.period_length, pain) if seg and phase else None
        state = _period_state(d, phase, seg, windows)
        if state == PERIOD_STATE_RECORDED:
            phase_source = "recorded"
        elif state == PERIOD_STATE_PREDICTED or (seg is not None and seg.source == SEGMENT_PREDICTED):
            phase_source = "predicted"
        elif seg is not None:
            phase_source = "derived"
        else:
            phase_source = None
        days.append(
            {
                "date": d.isoformat(),
                "phase_key": phase,
                "phase_label": PHASE_LABELS[phase] if phase else None,
                "phase_source": phase_source,
                "sport_level": level,
                "sport_label": SPORT_LABELS[level] if level else None,
                "is_period": phase == PHASE_MENSTRUAL,
                "period_state": state,
                "period_label": PERIOD_STATE_LABELS[state] if state else None,
                "pain_level": pain,
                "pain_recorded": d in pain_map,
                "is_recorded_start": d in recorded_starts,
                "cycle_day": cycle_day,
                "segment_source": seg.source if seg else None,
            }
        )

    latest = rows[-1] if rows else None
    latest_period_length = _period_length_of(latest, setting.period_length) if latest else None
    next_period = next_period_date(db, user_id, setting) if latest else None
    overdue_days = (today - next_period).days if next_period and today > next_period else 0

    today_seg = segment_for_day(segments, today)
    today_phase = phase_in_segment(today, today_seg) if today_seg else None
    today_cycle_day = (today - today_seg.start).days + 1 if today_seg else None
    today_level = (
        sport_level_for(today_phase, today_cycle_day, today_seg.length, today_seg.period_length, _today_pain(db, user_id, today, pain_map))
        if today_seg and today_phase
        else None
    )
    ovulation_date = (
        today_seg.start + timedelta(days=today_seg.length - OVULATION_OFFSET - 1)
        if today_seg is not None and today_seg.inferable
        else None
    )

    return {
        "year": year,
        "month": month,
        "days": days,
        "overview": {
            "has_records": bool(rows),
            "reference_cycle_length": setting.cycle_length,
            "reference_period_length": setting.period_length,
            "latest_cycle_length": None,  # 最新一条要等下次记录才有真实值
            "latest_period_length": latest_period_length if latest and latest.end_date else None,
            "next_period": next_period.isoformat() if next_period else None,
            "overdue_days": overdue_days,
            "ovulation_date": ovulation_date.isoformat() if ovulation_date else None,
            "cycle_day_today": today_cycle_day,
            "cycle_length_today": today_seg.length if today_seg else None,
            "today_source": today_seg.source if today_seg else None,
            "progress": f"{today_cycle_day}/{today_seg.length}" if today_seg else None,
        },
        "today": {
            "date": today.isoformat(),
            "phase_key": today_phase,
            "phase_label": PHASE_LABELS[today_phase] if today_phase else None,
            "sport_level": today_level,
            "sport_label": SPORT_LABELS[today_level] if today_level else None,
        },
    }


def _today_pain(db: Session, user_id: int, today: date, pain_map: dict) -> int:
    if today in pain_map:
        return pain_map[today]
    row = db.query(DailyPainLog).filter(DailyPainLog.user_id == user_id, DailyPainLog.log_date == today).first()
    return row.pain_level if row else 0


# ---------- 侧边栏今日摘要 ----------
def get_today_summary(user_id: int) -> dict:
    """页面侧边栏“今天”小卡信息；今天无段时阶段为空。"""
    from database import SessionLocal

    db = SessionLocal()
    try:
        setting = get_settings(db, user_id)
        today = today_local()
        has_records = bool(db.query(PeriodRecord.id).filter(PeriodRecord.user_id == user_id).first())
        seg = segment_for_day(build_segments(db, user_id, setting=setting, today=today), today)
        if seg is None:
            return {
                "has_records": has_records,
                "cycle_day": None,
                "cycle_length": None,
                "phase_key": None,
                "phase_label": None,
                "sport_level": None,
                "sport_label": None,
            }
        row = db.query(DailyPainLog).filter(DailyPainLog.user_id == user_id, DailyPainLog.log_date == today).first()
        pain = row.pain_level if row else 0
        cycle_day = (today - seg.start).days + 1
        phase = phase_in_segment(today, seg)
        level = sport_level_for(phase, cycle_day, seg.length, seg.period_length, pain) if phase else None
        return {
            "has_records": has_records,
            "cycle_day": cycle_day,
            "cycle_length": seg.length,
            "phase_key": phase,
            "phase_label": PHASE_LABELS.get(phase),
            "sport_level": level,
            "sport_label": SPORT_LABELS.get(level),
        }
    finally:
        db.close()
