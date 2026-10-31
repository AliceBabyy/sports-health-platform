"""游泳 service：配速/平均划频计算、分页列表、汇总统计。"""
from sqlalchemy.orm import Session

from app.core.constants import SWIM_STROKE_LABELS
from app.modules.swim.models import SwimRecord


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


def to_dict(row: SwimRecord) -> dict:
    return {
        "id": row.id,
        "record_date": row.record_date.isoformat(),
        "distance_m": row.distance_m,
        "duration_s": row.duration_s,
        "pace": calc_pace(row.duration_s, row.distance_m),
        "avg_heart_rate": row.avg_heart_rate,
        "total_strokes": row.total_strokes,
        "main_stroke": row.main_stroke,
        "main_stroke_label": SWIM_STROKE_LABELS.get(row.main_stroke, row.main_stroke),
        "laps": row.laps,
        "avg_stroke_rate": calc_stroke_rate(row.total_strokes, row.duration_s),
        "calories": float(row.calories) if row.calories is not None else None,
    }


def list_records(db: Session, user_id: int, page: int = 1, page_size: int = 10):
    from app.core.pagination import paginate

    q = db.query(SwimRecord).filter(SwimRecord.user_id == user_id)
    return paginate(q, page, page_size, order_by=SwimRecord.record_date.desc())


def create_record(db: Session, user_id: int, data) -> SwimRecord:
    row = SwimRecord(user_id=user_id, **data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_record(db: Session, user_id: int, record_id: int, data) -> SwimRecord | None:
    row = db.query(SwimRecord).filter(SwimRecord.id == record_id, SwimRecord.user_id == user_id).first()
    if row is None:
        return None
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


def stats(db: Session, user_id: int) -> dict:
    """顶部汇总（SW-03）：总距离/次数/平均配速/累计时长/平均心率/主泳姿分布。"""
    rows = db.query(SwimRecord).filter(SwimRecord.user_id == user_id).all()
    count = len(rows)
    if not count:
        return {
            "count": 0, "total_distance_m": 0, "total_duration_s": 0, "avg_pace": None,
            "avg_heart_rate": None, "stroke_count": {},
        }
    total_distance = sum(r.distance_m for r in rows)
    total_duration = sum(r.duration_s for r in rows)
    avg_pace = calc_pace(total_duration, total_distance)  # 总时长/总距离 → 平均配速
    rates = [r.avg_heart_rate for r in rows if r.avg_heart_rate]
    stroke_count: dict[str, int] = {}
    for r in rows:
        stroke_count[r.main_stroke] = stroke_count.get(r.main_stroke, 0) + 1
    return {
        "count": count,
        "total_distance_m": total_distance,
        "total_duration_s": total_duration,
        "avg_pace": avg_pace,
        "avg_heart_rate": round(sum(rates) / len(rates)) if rates else None,
        "stroke_count": stroke_count,
    }
