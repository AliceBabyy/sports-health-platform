"""游泳 service：配速/平均划频计算、分页列表、汇总统计。"""
from sqlalchemy.orm import Session

from app.core.constants import SWIM_STROKE_LABELS
from app.core.exceptions import AppError
from app.core.sport_ops import require_recorded, validate_status_change
from app.modules.swim.models import SwimNote, SwimRecord


def calc_pace(duration_s: int, distance_m: int) -> float | None:
    """配速 min/100m = 时长秒 ÷ 距离米 × 100 ÷ 60，保留 1 位；防除零。"""
    if not distance_m or not duration_s:
        return None
    return round(duration_s / distance_m * 100 / 60, 1)


def calc_stroke_rate(total_strokes: int | None, duration_s: int) -> float | None:
    """平均划频 次/分钟 = 总划水次数 ÷ (时长秒/60)。"""
    if total_strokes is None or not duration_s:
        return None
    return round(total_strokes / (duration_s / 60), 1)


def _seconds_between(start, end) -> int | None:
    """起止时间 → 正整数秒；缺失或逆序返回 None。"""
    if start is None or end is None:
        return None
    secs = int((end - start).total_seconds())
    return secs if secs > 0 else None


def _derive_duration(data) -> None:
    """未手填时长且起止时间齐备时，按起止推导 duration_s（计划/记录通用）。"""
    if getattr(data, "duration_s", None) is None:
        data.duration_s = _seconds_between(getattr(data, "start_time", None), getattr(data, "end_time", None))


def _derive_duration_dict(data: dict) -> None:
    """导入行（dict）版本：同 `_derive_duration`，原地补 duration_s。"""
    if data.get("duration_s") is None:
        data["duration_s"] = _seconds_between(data.get("start_time"), data.get("end_time"))


def to_dict(row: SwimRecord) -> dict:
    # 平均划频：优先取用户手填值；未填时由总划水/时长派生
    avg_stroke_rate = row.avg_stroke_rate
    if avg_stroke_rate is None:
        avg_stroke_rate = calc_stroke_rate(row.total_strokes, row.duration_s)
    note = row.note
    return {
        "id": row.id,
        "date": row.date.isoformat(),
        "start_time": row.start_time.isoformat() if row.start_time else None,
        "end_time": row.end_time.isoformat() if row.end_time else None,
        "status": row.status,
        "remark": row.remark,
        "distance_m": row.distance_m,
        "duration_s": row.duration_s,
        "pace": calc_pace(row.duration_s, row.distance_m),
        "avg_heart_rate": row.avg_heart_rate,
        "max_heart_rate": row.max_heart_rate,
        "total_strokes": row.total_strokes,
        "main_stroke": row.main_stroke,
        "main_stroke_label": SWIM_STROKE_LABELS.get(row.main_stroke, row.main_stroke),
        "laps": row.laps,
        "avg_stroke_rate": avg_stroke_rate,
        "calories": float(row.calories) if row.calories is not None else None,
        "note": (
            {
                "id": note.id,
                "rating": note.rating,
                "stroke_insight": note.stroke_insight,
                "notes": note.notes,
            }
            if note
            else None
        ),
    }


def list_records(db: Session, user_id: int, page: int = 1, page_size: int = 10):
    from app.core.pagination import paginate

    q = db.query(SwimRecord).filter(SwimRecord.user_id == user_id)
    return paginate(q, page, page_size, order_by=(SwimRecord.date.desc(), SwimRecord.id.desc()))


def get_by_date(db: Session, user_id: int, date) -> list[SwimRecord]:
    """某日全部行（计划 + 记录，按 id 升序）。"""
    return (
        db.query(SwimRecord)
        .filter(SwimRecord.user_id == user_id, SwimRecord.date == date)
        .order_by(SwimRecord.id)
        .all()
    )


def create_record(db: Session, user_id: int, data) -> SwimRecord:
    _derive_duration(data)
    row = SwimRecord(user_id=user_id, **data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_record(db: Session, user_id: int, record_id: int, data) -> SwimRecord | None:
    row = db.query(SwimRecord).filter(SwimRecord.id == record_id, SwimRecord.user_id == user_id).first()
    if row is None:
        return None
    validate_status_change(row.status, data.status)
    _derive_duration(data)
    for k, v in data.model_dump().items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


def delete_record(db: Session, user_id: int, record_id: int) -> bool:
    row = db.query(SwimRecord).filter(SwimRecord.id == record_id, SwimRecord.user_id == user_id).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def bulk_create_records(db: Session, user_id: int, rows: list[dict]) -> list[int]:
    """批量导入记录（status 固定 recorded），rows 为已校验的字段 dict，返回新建记录 id 列表。"""
    created: list[int] = []
    for data in rows:
        data = dict(data)
        _derive_duration_dict(data)
        row = SwimRecord(user_id=user_id, status="recorded", **data)
        db.add(row)
        db.flush()  # 拿到 id
        created.append(row.id)
    db.commit()
    return created


# ---------- 练后心得（1:1，2026-11） ----------

def get_note(db: Session, user_id: int, record_id: int) -> SwimNote | None:
    row = db.query(SwimRecord).filter(SwimRecord.id == record_id, SwimRecord.user_id == user_id).first()
    return row.note if row else None


def upsert_note(db: Session, user_id: int, record_id: int, *, rating, stroke_insight, notes) -> SwimNote:
    """心得 upsert：记录归属校验 → 有则改、无则建。rating 限定 1~5。"""
    row = db.query(SwimRecord).filter(SwimRecord.id == record_id, SwimRecord.user_id == user_id).first()
    if row is None:
        raise AppError(404, "游泳记录不存在")
    require_recorded(row)
    if rating is not None and not (1 <= rating <= 5):
        raise AppError(400, "自我评估需为 1~5 星")
    note = row.note
    if note is None:
        note = SwimNote(swim_id=row.id)
        row.note = note
    note.rating = rating
    note.stroke_insight = stroke_insight or None
    note.notes = notes or None
    db.commit()
    db.refresh(note)
    return note


def stats(db: Session, user_id: int) -> dict:
    """游泳档案聚合（SW-03）：仅统计记录态。

    返回累计次数/距离/时长/平均配速，以及：
    - fastest_pace / slowest_pace：历史记录中最快 / 最慢配速（min/100m，越小越快）
    - top_stroke / top_stroke_label：出现次数最多的主泳姿
    - latest：最近一次游泳记录的成绩摘要（日期/距离/时长/配速/泳姿/划频）
    """
    rows = (
        db.query(SwimRecord)
        .filter(SwimRecord.user_id == user_id, SwimRecord.status == "recorded")
        .order_by(SwimRecord.date.desc(), SwimRecord.id.desc())
        .all()
    )
    count = len(rows)
    if not count:
        return {
            "count": 0, "total_distance_m": 0, "total_duration_s": 0, "avg_pace": None,
            "avg_heart_rate": None, "stroke_count": {},
            "fastest_pace": None, "slowest_pace": None,
            "top_stroke": None, "top_stroke_label": None,
            "latest": None,
        }
    total_distance = sum(r.distance_m for r in rows if r.distance_m)
    total_duration = sum(r.duration_s for r in rows if r.duration_s)
    avg_pace = calc_pace(total_duration, total_distance)  # 总时长/总距离 → 平均配速
    rates = [r.avg_heart_rate for r in rows if r.avg_heart_rate]

    # 各记录配速（仅取距离/时长齐全的），用于最快/最慢
    paces = [p for r in rows if (p := calc_pace(r.duration_s, r.distance_m)) is not None]
    fastest_pace = min(paces) if paces else None
    slowest_pace = max(paces) if paces else None

    # 主泳姿分布（忽略空值）→ 最多
    stroke_count: dict[str, int] = {}
    for r in rows:
        if r.main_stroke:
            stroke_count[r.main_stroke] = stroke_count.get(r.main_stroke, 0) + 1
    top_stroke = max(stroke_count, key=stroke_count.get) if stroke_count else None

    # 最新一次记录（rows 已按日期倒序）
    latest_row = rows[0]
    latest = {
        "date": latest_row.date.isoformat(),
        "distance_m": latest_row.distance_m,
        "duration_s": latest_row.duration_s,
        "pace": calc_pace(latest_row.duration_s, latest_row.distance_m),
        "main_stroke": latest_row.main_stroke,
        "main_stroke_label": SWIM_STROKE_LABELS.get(latest_row.main_stroke, latest_row.main_stroke),
        "avg_stroke_rate": latest_row.avg_stroke_rate
        if latest_row.avg_stroke_rate is not None
        else calc_stroke_rate(latest_row.total_strokes, latest_row.duration_s),
    }
    return {
        "count": count,
        "total_distance_m": total_distance,
        "total_duration_s": total_duration,
        "avg_pace": avg_pace,
        "avg_heart_rate": round(sum(rates) / len(rates)) if rates else None,
        "stroke_count": stroke_count,
        "fastest_pace": fastest_pace,
        "slowest_pace": slowest_pace,
        "top_stroke": top_stroke,
        "top_stroke_label": SWIM_STROKE_LABELS.get(top_stroke) if top_stroke else None,
        "latest": latest,
    }
