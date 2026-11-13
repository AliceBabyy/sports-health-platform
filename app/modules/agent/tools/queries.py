"""Agent 只读查询：受控、按 user_id 隔离、返回结构化事实。

只做查询与结构化，不做任何写操作。口径复用各运动模块的现有函数，
保证数据问答与页面/总览的统计一致。
"""
from datetime import date

from sqlalchemy.orm import Session

from app.core.constants import (
    BODY_LABELS,
    BODY_UNITS,
    TR_STATUS_PLANNED,
    TR_STATUS_RECORDED,
    TREND_KEYS,
)
from app.modules.dance.models import DanceRecord
from app.modules.overview.service import SPORT_LABELS, _fitness_minutes
from app.modules.swim.models import SwimRecord
from app.modules.swim.service import calc_pace, calc_stroke_rate
from app.modules.training.models import TrainingRecord

SPORT_KEYS = ("fitness", "swim", "dance")


def _empty_stat() -> dict:
    return {"records": 0, "plans": 0, "minutes": 0, "kcal": 0.0}


def _range_filter(query, model, user_id: int, start: date, end: date):
    return query.filter(
        model.user_id == user_id,
        model.date >= start,
        model.date <= end,
    )


def workout_summary(db: Session, user_id: int, start: date, end: date, sport: str) -> dict:
    stats = {k: _empty_stat() for k in SPORT_KEYS}
    active_days: set[date] = set()

    if sport in ("all", "fitness"):
        rows = _range_filter(db.query(TrainingRecord), TrainingRecord, user_id, start, end).all()
        for r in rows:
            s = stats["fitness"]
            if r.status == TR_STATUS_PLANNED:
                s["plans"] += 1
            else:
                s["records"] += 1
                s["minutes"] += _fitness_minutes(r)
                active_days.add(r.date)

    if sport in ("all", "swim"):
        rows = _range_filter(db.query(SwimRecord), SwimRecord, user_id, start, end).all()
        for r in rows:
            s = stats["swim"]
            if r.status == TR_STATUS_PLANNED:
                s["plans"] += 1
            else:
                s["records"] += 1
                if r.duration_s is not None:
                    s["minutes"] += r.duration_s // 60
                if r.calories is not None:
                    s["kcal"] += float(r.calories)
                active_days.add(r.date)

    if sport in ("all", "dance"):
        rows = _range_filter(db.query(DanceRecord), DanceRecord, user_id, start, end).all()
        for r in rows:
            s = stats["dance"]
            if r.status == TR_STATUS_PLANNED:
                s["plans"] += 1
            else:
                s["records"] += 1
                if r.duration_s is not None:
                    s["minutes"] += r.duration_s // 60
                if r.calories is not None:
                    s["kcal"] += float(r.calories)
                active_days.add(r.date)

    for k in SPORT_KEYS:
        stats[k]["kcal"] = round(stats[k]["kcal"], 1)

    total = {
        "records": sum(stats[k]["records"] for k in SPORT_KEYS),
        "plans": sum(stats[k]["plans"] for k in SPORT_KEYS),
        "minutes": sum(stats[k]["minutes"] for k in SPORT_KEYS),
        "kcal": round(sum(stats[k]["kcal"] for k in SPORT_KEYS), 1),
        "active_days": len(active_days),
    }
    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "sport_labels": SPORT_LABELS,
        "per_sport": stats,
        "total": total,
        "note": "时长与热量仅统计 recorded 记录，plans 单独计数；健身无热量字段。",
    }


def recent_swims(db: Session, user_id: int, limit: int) -> dict:
    rows = (
        db.query(SwimRecord)
        .filter(SwimRecord.user_id == user_id, SwimRecord.status == TR_STATUS_RECORDED)
        .order_by(SwimRecord.date.desc(), SwimRecord.id.desc())
        .limit(limit)
        .all()
    )
    records = []
    for r in rows:
        records.append({
            "id": r.id,
            "date": r.date.isoformat(),
            "distance_m": r.distance_m,
            "duration_s": r.duration_s,
            "pace_min_per_100m": calc_pace(r.duration_s, r.distance_m),
            "avg_stroke_rate": r.avg_stroke_rate or calc_stroke_rate(r.total_strokes, r.duration_s),
            "main_stroke": r.main_stroke,
            "calories": float(r.calories) if r.calories is not None else None,
        })
    return {
        "count": len(records),
        "limit": limit,
        "records": records,
        "note": "仅含 recorded 游泳，按日期倒序；pace 单位 分钟/100 米，划频 次/分钟。",
    }


def body_measurements(db: Session, user_id: int, metric: str, start: date, end: date) -> dict:
    model = _model_for(metric)
    column = _column_for(metric)
    rows = (
        db.query(model.record_date, getattr(model, column))
        .filter(
            model.user_id == user_id,
            model.record_date >= start,
            model.record_date <= end,
            getattr(model, column).isnot(None),
        )
        .order_by(model.record_date.asc())
        .all()
    )
    points = [
        {"date": d.isoformat(), "value": float(v)}
        for d, v in rows
    ]
    return {
        "metric": metric,
        "label": BODY_LABELS[metric],
        "unit": BODY_UNITS[metric],
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "sample_count": len(points),
        "points": points,
        "note": "点均为实际测量值，未测量日期不补沿用值；数据不足时不能据此判断趋势。",
    }


# 工具可暴露的实际测量指标白名单（与 constants.TREND_KEYS 对齐）
BODY_METRIC_WHITELIST = tuple(TREND_KEYS)


def _column_for(metric: str) -> str:
    from app.core.constants import BODY_COLUMNS

    return BODY_COLUMNS[metric]


def _model_for(metric: str):
    from app.modules.body.service import GROUP_MODELS
    from app.core.constants import BODY_FIELDS

    return GROUP_MODELS[BODY_FIELDS[metric][3]]
