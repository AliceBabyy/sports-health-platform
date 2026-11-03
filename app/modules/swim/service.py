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
    # 平均划频：优先取用户手填值；未填时由总划水/时长派生
    avg_stroke_rate = row.avg_stroke_rate
    if avg_stroke_rate is None:
        avg_stroke_rate = calc_stroke_rate(row.total_strokes, row.duration_s)
    return {
        "id": row.id,
        "record_date": row.record_date.isoformat(),
        "status": row.status,
        "remark": row.remark,
        "distance_m": row.distance_m,
        "duration_s": row.duration_s,
        "pace": calc_pace(row.duration_s, row.distance_m),
        "avg_heart_rate": row.avg_heart_rate,
        "total_strokes": row.total_strokes,
        "main_stroke": row.main_stroke,
        "main_stroke_label": SWIM_STROKE_LABELS.get(row.main_stroke, row.main_stroke),
        "laps": row.laps,
        "avg_stroke_rate": avg_stroke_rate,
        "calories": float(row.calories) if row.calories is not None else None,
    }


def list_records(db: Session, user_id: int, page: int = 1, page_size: int = 10):
    from app.core.pagination import paginate

    q = db.query(SwimRecord).filter(SwimRecord.user_id == user_id)
    return paginate(q, page, page_size, order_by=SwimRecord.record_date.desc())


def get_by_date(db: Session, user_id: int, record_date) -> list[SwimRecord]:
    """某日全部行（计划 + 记录，按 id 升序）。"""
    return (
        db.query(SwimRecord)
        .filter(SwimRecord.user_id == user_id, SwimRecord.record_date == record_date)
        .order_by(SwimRecord.id)
        .all()
    )


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


def bulk_create_records(db: Session, user_id: int, rows: list[dict]) -> int:
    """批量导入记录（status 固定 recorded），rows 为已校验的字段 dict，返回成功条数。"""
    count = 0
    for data in rows:
        row = SwimRecord(user_id=user_id, status="recorded", **data)
        db.add(row)
        count += 1
    db.commit()
    return count


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
        .order_by(SwimRecord.record_date.desc(), SwimRecord.id.desc())
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
        "record_date": latest_row.record_date.isoformat(),
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
