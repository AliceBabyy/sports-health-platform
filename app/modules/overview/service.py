"""跨运动总览 service：健身/游泳/舞蹈 按日期窗口聚合（day/week/month）+ 单日详情。

口径：
- 统一状态：planned（计划）/ recorded（记录）；健身的 status 存 planned|recorded；
  游泳/舞蹈 status 同构（2026-11 加列）。
- 健身时长：recorded 时按 saved_at - started_at（秒→分钟）；计划态计 0。
- 游泳/舞蹈时长：duration_s；热量：calories（健身无热量字段，stats 热量=游泳+舞蹈）。
- 图表序列：week → 每日分钟；month → 按周分组（跨月周只聚合月内日期）。
"""
import calendar as _calendar
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core.constants import TR_STATUS_PLANNED, TR_STATUS_RECORDED, monday_of
from app.modules.dance import service as dance_service
from app.modules.dance.models import DanceRecord
from app.modules.swim import service as swim_service
from app.modules.swim.models import SwimRecord
from app.modules.training import service as training_service
from app.modules.training.models import TrainingPlan

SPORT_KEYS = ("fitness", "swim", "dance")
SPORT_LABELS = {"fitness": "健身", "swim": "游泳", "dance": "舞蹈"}


def _empty_counts() -> dict:
    return {"plans": 0, "records": 0, "minutes": 0, "kcal": 0.0}


def _fitness_minutes(plan) -> int:
    if plan.status == TR_STATUS_RECORDED and plan.started_at is not None and plan.saved_at is not None:
        return max(0, int((plan.saved_at - plan.started_at).total_seconds())) // 60
    return 0


def _counts(rows: list, sport: str) -> dict:
    """单日单运动全部行 → {plans, records, minutes, kcal}。"""
    out = _empty_counts()
    for r in rows:
        status = getattr(r, "status", None) or TR_STATUS_RECORDED
        if status == TR_STATUS_PLANNED:
            out["plans"] += 1
            continue
        out["records"] += 1
        if sport == "fitness":
            out["minutes"] += _fitness_minutes(r)
        else:
            if r.duration_s is not None:
                out["minutes"] += r.duration_s // 60
            if r.calories is not None:
                out["kcal"] += float(r.calories)
    out["minutes"] = int(out["minutes"])
    out["kcal"] = round(out["kcal"], 1)
    return out


def _day_rows(db: Session, user_id: int, day: date) -> dict:
    return {
        "fitness": (
            db.query(TrainingPlan)
            .filter(TrainingPlan.user_id == user_id, TrainingPlan.plan_date == day)
            .order_by(TrainingPlan.id)
            .all()
        ),
        "swim": (
            db.query(SwimRecord)
            .filter(SwimRecord.user_id == user_id, SwimRecord.record_date == day)
            .order_by(SwimRecord.id)
            .all()
        ),
        "dance": (
            db.query(DanceRecord)
            .filter(DanceRecord.user_id == user_id, DanceRecord.record_date == day)
            .order_by(DanceRecord.id)
            .all()
        ),
    }


def _range_days(granularity: str, day: date) -> tuple[date, date, list[date]]:
    if granularity == "day":
        return day, day, [day]
    if granularity == "week":
        start = monday_of(day)
        end = start + timedelta(days=6)
        return start, end, [start + timedelta(days=i) for i in range(7)]
    start = day.replace(day=1)
    _, last = _calendar.monthrange(day.year, day.month)
    end = day.replace(day=last)
    return start, end, [start + timedelta(days=i) for i in range(last)]


def _chart_week(per_day: list[dict]) -> dict:
    labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return {
        "labels": labels,
        "fitness": [d["sports"]["fitness"]["minutes"] for d in per_day],
        "swim": [d["sports"]["swim"]["minutes"] for d in per_day],
        "dance": [d["sports"]["dance"]["minutes"] for d in per_day],
    }


def _chart_month(days: list[date], per_day: list[dict]) -> dict:
    """按自然周（周一起）分组，跨月周只聚合月内日期。"""
    day_map = {d: c for d, c in zip(days, per_day)}
    first = days[0]
    week_start = monday_of(first)
    weeks: list[tuple[str, list[date]]] = []
    cursor = week_start
    while cursor <= days[-1]:
        chunk = [cursor + timedelta(days=i) for i in range(7)]
        inner = [c for c in chunk if c in day_map]
        if inner:
            label = f"{inner[0].month}.{inner[0].day:02d}–{inner[-1].month}.{inner[-1].day:02d}"
            weeks.append((label, inner))
        cursor += timedelta(days=7)
    labels = [w[0] for w in weeks]
    fitness, swim, dance = [], [], []
    for _, inner in weeks:
        fitness.append(sum(day_map[c]["sports"]["fitness"]["minutes"] for c in inner))
        swim.append(sum(day_map[c]["sports"]["swim"]["minutes"] for c in inner))
        dance.append(sum(day_map[c]["sports"]["dance"]["minutes"] for c in inner))
    return {"labels": labels, "fitness": fitness, "swim": swim, "dance": dance}


def aggregate(db: Session, user_id: int, granularity: str, day: date) -> dict:
    """总览聚合：逐日 per-sport 计数 + 汇总卡 + 图表序列。"""
    start, end, days = _range_days(granularity, day)
    per_day = []
    for d in days:
        rows = _day_rows(db, user_id, d)
        per_day.append(
            {
                "date": d.isoformat(),
                "weekday": _calendar.day_name[d.weekday()][:3],
                "sports": {k: _counts(rows[k], k) for k in SPORT_KEYS},
            }
        )

    stats = {
        "records": 0,
        "plans": 0,
        "minutes": 0,
        "kcal": 0.0,
        "days": 0,
        "per_sport": {k: dict(_empty_counts()) for k in SPORT_KEYS},
    }
    for pd in per_day:
        active_today = False
        for k in SPORT_KEYS:
            c = pd["sports"][k]
            for key in ("records", "plans", "minutes", "kcal"):
                stats["per_sport"][k][key] += c[key]
                stats[key] += c[key]
            if c["records"]:
                active_today = True
        if active_today:
            stats["days"] += 1
    stats["minutes"] = int(stats["minutes"])
    stats["kcal"] = round(stats["kcal"], 1)
    for k in SPORT_KEYS:
        stats["per_sport"][k]["minutes"] = int(stats["per_sport"][k]["minutes"])
        stats["per_sport"][k]["kcal"] = round(stats["per_sport"][k]["kcal"], 1)

    chart = None
    if granularity == "week":
        chart = _chart_week(per_day)
    elif granularity == "month":
        chart = _chart_month(days, per_day)

    return {
        "granularity": granularity,
        "date": day.isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": per_day,
        "stats": stats,
        "chart": chart,
    }


def day_detail(db: Session, user_id: int, day: date) -> dict:
    """单日详情：三运动当日全部条目（供总览弹窗 / 详情页）。"""
    rows = _day_rows(db, user_id, day)
    return {
        "date": day.isoformat(),
        "fitness": [training_service.plan_to_dict(p) for p in rows["fitness"]],
        "swim": [swim_service.to_dict(r) for r in rows["swim"]],
        "dance": [dance_service.to_dict(r) for r in rows["dance"]],
        "labels": SPORT_LABELS,
    }
