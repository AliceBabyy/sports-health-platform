"""身材数据 service：upsert（BD-02）、最新值+环比（BD-04）、BMI、分页、剪影数据。"""
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.constants import METRIC_KEYS
from app.modules.body.models import BodyMetricRecord


def _to_float(v) -> float | None:
    if v is None:
        return None
    return float(v)


def normalize_day_values(db: Session, user_id: int, metric_key: str) -> dict[date, float]:
    """BD-02 口径：同一天同指标多条取最后一条，返回 {record_date: value}。"""
    rows = (
        db.query(BodyMetricRecord)
        .filter(BodyMetricRecord.user_id == user_id, BodyMetricRecord.metric_key == metric_key)
        .order_by(BodyMetricRecord.record_date.asc(), BodyMetricRecord.id.asc())
        .all()
    )
    result: dict[date, float] = {}
    for r in rows:
        result[r.record_date] = _to_float(r.value)  # 后面的覆盖前面 → 最后一条生效
    return result


def upsert_metrics(db: Session, user_id: int, record_date: date, values: dict[str, float]) -> None:
    """BD-01/02：按 user_id+metric_key+record_date upsert，忽略未知指标 key。"""
    for key, value in values.items():
        if key not in METRIC_KEYS or value is None:
            continue
        row = (
            db.query(BodyMetricRecord)
            .filter(
                BodyMetricRecord.user_id == user_id,
                BodyMetricRecord.metric_key == key,
                BodyMetricRecord.record_date == record_date,
            )
            .first()
        )
        if row:
            row.value = Decimal(str(value))
        else:
            db.add(BodyMetricRecord(user_id=user_id, metric_key=key, record_date=record_date, value=Decimal(str(value))))
    db.commit()


def delete_day(db: Session, user_id: int, record_date: date) -> int:
    """删除某日全部指标记录，返回删除条数。"""
    deleted = (
        db.query(BodyMetricRecord)
        .filter(BodyMetricRecord.user_id == user_id, BodyMetricRecord.record_date == record_date)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def update_record(db: Session, user_id: int, record_id: int, value: float | None, record_date: date | None):
    row = db.query(BodyMetricRecord).filter(BodyMetricRecord.id == record_id, BodyMetricRecord.user_id == user_id).first()
    if row is None:
        return None
    if value is not None:
        row.value = Decimal(str(value))
    if record_date is not None:
        row.record_date = record_date
    db.commit()
    db.refresh(row)
    return row


def delete_record(db: Session, user_id: int, record_id: int) -> bool:
    row = db.query(BodyMetricRecord).filter(BodyMetricRecord.id == record_id, BodyMetricRecord.user_id == user_id).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def list_records(db: Session, user_id: int, page: int = 1, page_size: int = 10):
    """分页记录（按日期聚合，BD-02：同日同指标取最后一条）。

    返回 {list: [{record_date, values: {metric_key: value}}], total: 记录天数, ...}。
    """
    from math import ceil

    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    base = db.query(BodyMetricRecord).filter(BodyMetricRecord.user_id == user_id)
    total = (
        db.query(BodyMetricRecord.record_date)
        .filter(BodyMetricRecord.user_id == user_id)
        .distinct()
        .count()
    )
    dates = (
        db.query(BodyMetricRecord.record_date)
        .filter(BodyMetricRecord.user_id == user_id)
        .distinct()
        .order_by(BodyMetricRecord.record_date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    dates = [d[0] for d in dates]
    by_date: dict[date, dict[str, float]] = {}
    if dates:
        rows = (
            base.filter(BodyMetricRecord.record_date.in_(dates))
            .order_by(BodyMetricRecord.record_date.desc(), BodyMetricRecord.id.desc())
            .all()
        )
        for r in rows:  # 倒序取第一条即当日最后一条（BD-02）
            by_date.setdefault(r.record_date, {})
            if r.metric_key not in by_date[r.record_date]:
                by_date[r.record_date][r.metric_key] = _to_float(r.value)
    return {
        "list": [{"record_date": d.isoformat(), "values": by_date.get(d, {})} for d in dates],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": ceil(total / page_size) if total else 0,
    }


def latest_snapshot(db: Session, user_id: int) -> dict:
    """BD-04：各指标最新值 + 较上次差值/方向 + BMI 自动计算。"""
    snap = {}
    for key in METRIC_KEYS:
        rows = (
            db.query(BodyMetricRecord)
            .filter(BodyMetricRecord.user_id == user_id, BodyMetricRecord.metric_key == key)
            .order_by(BodyMetricRecord.record_date.desc(), BodyMetricRecord.id.desc())
            .limit(2)
            .all()
        )
        latest = rows[0] if rows else None
        prev = rows[1] if len(rows) > 1 else None
        snap[key] = {
            "value": _to_float(latest.value) if latest else None,
            "record_date": latest.record_date.isoformat() if latest else None,
            "delta": _to_float(latest.value - prev.value) if latest and prev else None,
            "prev_value": _to_float(prev.value) if prev else None,
        }

    # BMI = 体重kg ÷ 身高m²（健康区间 18.5~23.9）
    weight = snap["weight"]["value"]
    height = snap["height"]["value"]
    bmi = None
    if weight is not None and height:
        bmi = round(weight / ((height / 100) ** 2), 1)
    snap["bmi"] = bmi
    snap["bmi_state"] = _bmi_state(bmi)
    return snap


def _bmi_state(bmi: float | None) -> str | None:
    if bmi is None:
        return None
    if bmi < 18.5:
        return "偏轻"
    if bmi < 24:
        return "正常"
    if bmi < 28:
        return "超重"
    return "肥胖"
