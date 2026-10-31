"""舞蹈 service：分页 CRUD + 汇总统计（DA-01）。"""
from sqlalchemy.orm import Session

from app.modules.dance.models import DanceRecord


def to_dict(row: DanceRecord) -> dict:
    return {
        "id": row.id,
        "record_date": row.record_date.isoformat(),
        "dance_type": row.dance_type,
        "stars": row.stars,
        "style": row.style,
        "duration_s": row.duration_s,
        "avg_heart_rate": row.avg_heart_rate,
        "max_heart_rate": row.max_heart_rate,
        "calories": float(row.calories) if row.calories is not None else None,
    }


def list_records(db: Session, user_id: int, page: int = 1, page_size: int = 10, dance_type: str | None = None):
    from app.core.pagination import paginate

    q = db.query(DanceRecord).filter(DanceRecord.user_id == user_id)
    if dance_type:
        q = q.filter(DanceRecord.dance_type == dance_type)
    return paginate(q, page, page_size, order_by=DanceRecord.record_date.desc())


def create_record(db: Session, user_id: int, data) -> DanceRecord:
    row = DanceRecord(user_id=user_id, **data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_record(db: Session, user_id: int, record_id: int, data) -> DanceRecord | None:
    row = db.query(DanceRecord).filter(DanceRecord.id == record_id, DanceRecord.user_id == user_id).first()
    if row is None:
        return None
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
    """顶部汇总：累计课程/总时长/平均时长/平均心率/最激烈心率/平均星级/总卡路里/舞种分布。"""
    rows = db.query(DanceRecord).filter(DanceRecord.user_id == user_id).all()
    count = len(rows)
    if not count:
        return {
            "count": 0, "total_duration_s": 0, "avg_duration_s": 0, "avg_heart_rate": None,
            "max_heart_rate": None, "avg_stars": None, "total_calories": 0.0, "dance_types": [],
        }
    total_duration = sum(r.duration_s for r in rows)
    rates = [r.avg_heart_rate for r in rows if r.avg_heart_rate]
    max_rates = [r.max_heart_rate for r in rows if r.max_heart_rate]
    calories = [float(r.calories) for r in rows if r.calories is not None]
    type_count: dict[str, int] = {}
    for r in rows:
        type_count[r.dance_type] = type_count.get(r.dance_type, 0) + 1
    return {
        "count": count,
        "total_duration_s": total_duration,
        "avg_duration_s": round(total_duration / count),
        "avg_heart_rate": round(sum(rates) / len(rates)) if rates else None,
        "max_heart_rate": max(max_rates) if max_rates else None,
        "avg_stars": round(sum(r.stars for r in rows) / count, 1),
        "total_calories": round(sum(calories), 1) if calories else 0.0,
        "dance_types": sorted(type_count.items(), key=lambda x: -x[1]),
    }
