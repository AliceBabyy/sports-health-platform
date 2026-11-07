"""跨运动总览 service：健身/游泳/舞蹈 按日期窗口聚合（day/week/month）+ 单日详情。

口径：
- 统一状态：planned（计划）/ recorded（记录）；健身的 status 存 planned|recorded；
  游泳/舞蹈 status 同构（2026-11 加列）。
- 健身时长：recorded 时按 saved_at - started_at（秒→分钟）；计划态计 0。
- 游泳/舞蹈时长：duration_s；热量：calories（健身无热量字段，stats 热量=游泳+舞蹈）。
- 图表序列：week → 每日分钟；month → 按月内每日分钟。
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
from app.modules.training.models import TrainingRecord

SPORT_KEYS = ("fitness", "swim", "dance")
SPORT_LABELS = {"fitness": "健身", "swim": "游泳", "dance": "舞蹈"}


def _fmt_sec(sec: int | None) -> str:
    """秒 → m:ss / h:mm:ss（前端标签与弹窗展示用）。"""
    if not sec:
        return ""
    sec = int(sec)
    h, m = divmod(sec, 3600)
    m, s = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _empty_counts() -> dict:
    return {"plans": 0, "records": 0, "minutes": 0, "kcal": 0.0, "remarks": [], "items": []}


def _item_main(sport: str, r, status: str, minutes: int) -> str:
    """单条计划/记录在周/月每日卡独立标签里的简短描述（main）。"""
    if sport == "fitness":
        first = r.items[0].exercise_name if (r.items and r.items[0].exercise_name) else None
        base = first or ("训练记录" if status == "recorded" else "训练计划")
        if status == "recorded" and minutes:
            base += f" · {minutes}min"
        return base
    if sport == "swim":
        base = f"{r.distance_m}m" if r.distance_m else "游泳"
        if status == "recorded" and r.duration_s:
            base += f" · {_fmt_sec(r.duration_s)}"
        return base
    base = (r.dance_type or "舞蹈") + (f" ★{r.stars}" if r.stars else "")
    if status == "recorded" and r.duration_s:
        base += f" · {_fmt_sec(r.duration_s)}"
    return base


def _fitness_minutes(plan) -> int:
    """健身时长（分钟）：优先 duration_s；否则 recorded 时按 end_time - start_time 推导。"""
    if plan.status != TR_STATUS_RECORDED:
        return 0
    if getattr(plan, "duration_s", None):
        return int(plan.duration_s) // 60
    if plan.start_time is not None and plan.end_time is not None:
        return max(0, int((plan.end_time - plan.start_time).total_seconds())) // 60
    return 0


def _counts(rows: list, sport: str) -> dict:
    """单日单运动全部行 → {plans, records, minutes, kcal, remarks, items}。

    items：每条计划/记录一个独立条目（id/status/tag/main/minutes/remark），
    供周/月每日卡「每条独立标签」渲染；同一运动多条不再合并为单个计数标签。
    """
    out = _empty_counts()
    for r in rows:
        status = getattr(r, "status", None) or TR_STATUS_RECORDED
        minutes = 0
        if status == TR_STATUS_PLANNED:
            out["plans"] += 1
        else:
            out["records"] += 1
            if sport == "fitness":
                minutes = _fitness_minutes(r)
                out["minutes"] += minutes
            else:
                if r.duration_s is not None:
                    out["minutes"] += r.duration_s // 60
                if r.calories is not None:
                    out["kcal"] += float(r.calories)
        if sport == "fitness" and getattr(r, "remark", None):
            out["remarks"].append(r.remark)
        out["items"].append(
            {
                "id": r.id,
                "status": status,
                "tag": "计" if status == TR_STATUS_PLANNED else "记",
                "main": _item_main(sport, r, status, minutes),
                "minutes": int(minutes),
                "remark": getattr(r, "remark", None),
            }
        )
    out["minutes"] = int(out["minutes"])
    out["kcal"] = round(out["kcal"], 1)
    return out


def _day_rows(db: Session, user_id: int, day: date) -> dict:
    return {
        "fitness": (
            db.query(TrainingRecord)
            .filter(TrainingRecord.user_id == user_id, TrainingRecord.date == day)
            .order_by(TrainingRecord.id)
            .all()
        ),
        "swim": (
            db.query(SwimRecord)
            .filter(SwimRecord.user_id == user_id, SwimRecord.date == day)
            .order_by(SwimRecord.id)
            .all()
        ),
        "dance": (
            db.query(DanceRecord)
            .filter(DanceRecord.user_id == user_id, DanceRecord.date == day)
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
    """按月内每日分钟序列（labels=日号，2026-11 由按周分组改为每日）。"""
    return {
        "labels": [str(d.day) for d in days],
        "fitness": [c["sports"]["fitness"]["minutes"] for c in per_day],
        "swim": [c["sports"]["swim"]["minutes"] for c in per_day],
        "dance": [c["sports"]["dance"]["minutes"] for c in per_day],
    }


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
