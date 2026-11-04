"""舞蹈 service：分页 CRUD + 汇总统计（DA-01）。"""
from datetime import date, datetime
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.dance.models import DanceNote, DanceRecord


def to_dict(row: DanceRecord) -> dict:
    note = row.note
    return {
        "id": row.id,
        "record_date": row.record_date.isoformat(),
        "start_time": row.start_time.isoformat() if row.start_time else None,
        "end_time": row.end_time.isoformat() if row.end_time else None,
        "status": row.status,
        "remark": row.remark,
        "dance_type": row.dance_type,
        "stars": row.stars,
        "teacher": row.teacher,
        "style": row.style,
        "duration_s": row.duration_s,
        "avg_heart_rate": row.avg_heart_rate,
        "max_heart_rate": row.max_heart_rate,
        "calories": float(row.calories) if row.calories is not None else None,
        "note": (
            {
                "id": note.id,
                "rating": note.rating,
                "video_effect": note.video_effect,
                "insight": note.insight,
            }
            if note
            else None
        ),
    }


def _derive_duration(data) -> None:
    """若起止时间都有且未手动填 duration_s，则自动计算时长（秒）。"""
    if getattr(data, "duration_s", None) is None and data.start_time and data.end_time:
        if data.end_time > data.start_time:
            data.duration_s = int((data.end_time - data.start_time).total_seconds())


def list_records(db: Session, user_id: int, page: int = 1, page_size: int = 10, dance_type: str | None = None):
    from app.core.pagination import paginate

    q = db.query(DanceRecord).filter(DanceRecord.user_id == user_id)
    if dance_type:
        q = q.filter(DanceRecord.dance_type == dance_type)
    return paginate(q, page, page_size, order_by=DanceRecord.record_date.desc())


def get_by_date(db: Session, user_id: int, record_date) -> list[DanceRecord]:
    """某日全部行（计划 + 记录，按 id 升序）。"""
    return (
        db.query(DanceRecord)
        .filter(DanceRecord.user_id == user_id, DanceRecord.record_date == record_date)
        .order_by(DanceRecord.id)
        .all()
    )


def create_record(db: Session, user_id: int, data) -> DanceRecord:
    _derive_duration(data)
    row = DanceRecord(user_id=user_id, **data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_record(db: Session, user_id: int, record_id: int, data) -> DanceRecord | None:
    row = db.query(DanceRecord).filter(DanceRecord.id == record_id, DanceRecord.user_id == user_id).first()
    if row is None:
        return None
    _derive_duration(data)
    for k, v in data.model_dump().items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


def delete_record(db: Session, user_id: int, record_id: int) -> bool:
    row = db.query(DanceRecord).filter(DanceRecord.id == record_id, DanceRecord.user_id == user_id).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def stats(db: Session, user_id: int) -> dict:
    """顶部汇总：累计课程/总时长/平均心率/最激烈心率/平均星级/总卡路里/舞种分布/本月上课次数（仅统计记录态）。"""
    rows = (
        db.query(DanceRecord)
        .filter(DanceRecord.user_id == user_id, DanceRecord.status == "recorded")
        .all()
    )
    count = len(rows)
    if not count:
        return {
            "count": 0, "total_duration_s": 0, "avg_duration_s": 0, "avg_heart_rate": None,
            "max_heart_rate": None, "avg_stars": None, "total_calories": 0.0, "dance_types": [],
            "month_count": 0,
        }
    total_duration = sum(r.duration_s for r in rows if r.duration_s)
    rates = [r.avg_heart_rate for r in rows if r.avg_heart_rate]
    max_rates = [r.max_heart_rate for r in rows if r.max_heart_rate]
    calories = [float(r.calories) for r in rows if r.calories is not None]
    type_count: dict[str, int] = {}
    now = datetime.now()
    month_count = sum(
        1 for r in rows
        if r.record_date.year == now.year and r.record_date.month == now.month
    )
    for r in rows:
        if r.dance_type:
            type_count[r.dance_type] = type_count.get(r.dance_type, 0) + 1
    return {
        "count": count,
        "total_duration_s": total_duration,
        "avg_duration_s": round(total_duration / count),
        "avg_heart_rate": round(sum(rates) / len(rates)) if rates else None,
        "max_heart_rate": max(max_rates) if max_rates else None,
        "avg_stars": round(sum(r.stars for r in rows if r.stars) / count, 1),
        "total_calories": round(sum(calories), 1) if calories else 0.0,
        "dance_types": sorted(type_count.items(), key=lambda x: -x[1]),
        "month_count": month_count,
    }


# ---------- 练后心得（1:1，2026-11） ----------

def get_note(db: Session, user_id: int, record_id: int) -> DanceNote | None:
    row = db.query(DanceRecord).filter(DanceRecord.id == record_id, DanceRecord.user_id == user_id).first()
    return row.note if row else None


def upsert_note(db: Session, user_id: int, record_id: int, *, rating, video_effect, insight) -> DanceNote:
    """心得 upsert：记录归属校验 → 有则改、无则建。星级均限定 1~5。"""
    row = db.query(DanceRecord).filter(DanceRecord.id == record_id, DanceRecord.user_id == user_id).first()
    if row is None:
        raise AppError(404, "舞蹈记录不存在")
    for v in (rating, video_effect):
        if v is not None and not (1 <= v <= 5):
            raise AppError(400, "星级评分需为 1~5")
    note = row.note
    if note is None:
        note = DanceNote(dance_id=row.id)
        row.note = note
    note.rating = rating
    note.video_effect = video_effect
    note.insight = insight or None
    db.commit()
    db.refresh(note)
    return note
