"""确定性事实快照：周报/月报的全部数字都在这里计算。

原则：
- 只读、纯计算，复用 overview / 三运动 / 身材 / 状态记录 / 周期 service 的既有口径；
- 派生值（时长、配速、容量、阶段）不落库，实时算；
- 统计只计 recorded；计划单独计数，不做「计划完成率」（planned→recorded 原地改状态，无溯源）；
- 热量沿用总览口径：只汇总游泳与舞蹈（健身 calories 单独展示，不并入 total）；
- 周期只对女性且存在月经记录的账号生成，真实 / 推算 / 预测分开统计。
"""
from __future__ import annotations

import calendar as _calendar
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.constants import (
    PHASE_LABELS,
    SPORT_LABELS as SPORT_LEVEL_LABELS,
    SWIM_STROKE_LABELS,
    TR_STATUS_PLANNED,
    monday_of,
    today_local,
)
from app.modules.body import service as body_service
from app.modules.cycle import service as cycle_service
from app.modules.dance.models import DanceRecord
from app.modules.overview.service import _fitness_minutes
from app.modules.state_record.models import STATE_MODELS, STATE_TYPES, STATE_TYPE_LABELS
from app.modules.swim.models import SwimRecord
from app.modules.swim.service import calc_pace, to_dict as swim_to_dict
from app.modules.training.models import TrainingRecord
from app.modules.training.service import plan_to_dict

REPORT_WEEKLY = "weekly"
REPORT_MONTHLY = "monthly"

SPORT_KEYS = ("fitness", "swim", "dance")
BODY_METRICS = (
    ("weight", "体重", "kg"),
    ("body_fat", "体脂率", "%"),
    ("waist", "腰围", "cm"),
    ("hip", "臀围", "cm"),
)

# 周期七阶段 → 状态记录三档（与 state_record.service 保持同一归并口径）
PHASE_GROUP_MAP = {
    "menstrual": "menses",
    "follicular_pre": "foll",
    "ovulation_day": "foll",
    "follicular_post": "foll",
    "luteal_early": "luteal",
    "luteal_mid": "luteal",
    "luteal_late": "luteal",
}
PHASE_GROUP_LABELS = {"menses": "经期", "foll": "卵泡期/排卵", "luteal": "黄体期"}
PERIOD_STATE_LABELS = {"recorded": "真实记录", "inferred": "推算", "predicted": "预测"}


@dataclass(frozen=True)
class Period:
    """一个报告周期：周报=周一至周日，月报=自然月。"""

    type: str
    start: date
    end: date
    as_of: date
    partial: bool
    label: str
    range_label: str


# ---------- 通用格式化 ----------
def _num(value, digits: int = 1):
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int,)):
        return value
    if isinstance(value, (float, Decimal)):
        text = f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
        return float(text) if "." in text else int(text)
    return value


def _fmt(value, digits: int = 1) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, (float, Decimal)):
        v = float(value)
        if v.is_integer():
            return str(int(v))
        return f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def _display(value, unit: str | None = None) -> str:
    if value is None:
        return "—"
    text = _fmt(value)
    return f"{text} {unit}" if unit else text


def _duration_text(seconds: int | None) -> str:
    if not seconds:
        return "—"
    seconds = int(seconds)
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _metric(key: str, label: str, value, unit: str | None = None) -> dict:
    return {"key": key, "label": label, "value": _num(value), "unit": unit, "display": _display(value, unit)}


# ---------- 周期归一 ----------
def resolve_period(period_type: str, anchor: date | None = None, today: date | None = None) -> Period:
    """任意锚点日 → 所在周（周一至周日）/所在自然月。"""
    if period_type not in (REPORT_WEEKLY, REPORT_MONTHLY):
        raise ValueError("报告类型不合法")
    today = today or today_local()
    anchor = anchor or today

    if period_type == REPORT_WEEKLY:
        start = monday_of(anchor)
        end = start + timedelta(days=6)
        if start.year == end.year:
            label = f"{start.month}月{start.day}日–{end.month}月{end.day}日"
        else:
            label = f"{start.year}年{start.month}月{start.day}日–{end.year}年{end.month}月{end.day}日"
    else:
        start = anchor.replace(day=1)
        last = _calendar.monthrange(start.year, start.month)[1]
        end = anchor.replace(day=last)
        label = f"{start.year}年{start.month}月"

    partial = end > today
    as_of = min(end, today)
    return Period(
        type=period_type,
        start=start,
        end=end,
        as_of=as_of,
        partial=partial,
        label=label,
        range_label=f"{start.isoformat()} 至 {end.isoformat()}",
    )


def period_days(period: Period) -> list[date]:
    if period.as_of < period.start:
        return []
    return [period.start + timedelta(days=i) for i in range((period.as_of - period.start).days + 1)]


# ---------- 取数 ----------
def _sport_rows(db: Session, user_id: int, start: date, end: date) -> dict:
    return {
        "fitness": (
            db.query(TrainingRecord)
            .filter(TrainingRecord.user_id == user_id, TrainingRecord.date >= start, TrainingRecord.date <= end)
            .order_by(TrainingRecord.date.asc(), TrainingRecord.id.asc())
            .all()
        ),
        "swim": (
            db.query(SwimRecord)
            .filter(SwimRecord.user_id == user_id, SwimRecord.date >= start, SwimRecord.date <= end)
            .order_by(SwimRecord.date.asc(), SwimRecord.id.asc())
            .all()
        ),
        "dance": (
            db.query(DanceRecord)
            .filter(DanceRecord.user_id == user_id, DanceRecord.date >= start, DanceRecord.date <= end)
            .order_by(DanceRecord.date.asc(), DanceRecord.id.asc())
            .all()
        ),
    }


def _totals(rows: dict) -> dict:
    """周期总量：记录次数、计划条数、时长、热量（游+舞）、活跃天数。"""
    out = {"records": 0, "plans": 0, "minutes": 0, "kcal": 0.0, "active_dates": set()}
    for r in rows["fitness"]:
        if r.status == TR_STATUS_PLANNED:
            out["plans"] += 1
            continue
        out["records"] += 1
        out["minutes"] += _fitness_minutes(r)
        out["active_dates"].add(r.date)
    for key in ("swim", "dance"):
        for r in rows[key]:
            if r.status == TR_STATUS_PLANNED:
                out["plans"] += 1
                continue
            out["records"] += 1
            if r.duration_s:
                out["minutes"] += r.duration_s // 60
            if r.calories is not None:
                out["kcal"] += float(r.calories)
            out["active_dates"].add(r.date)
    out["minutes"] = int(out["minutes"])
    out["kcal"] = round(out["kcal"], 1)
    out["active_days"] = len(out["active_dates"])
    return out


def _fitness_facts(rows: list) -> dict:
    recorded = [r for r in rows if r.status != TR_STATUS_PLANNED]
    plans = len(rows) - len(recorded)
    minutes = sum(_fitness_minutes(r) for r in recorded)
    volume = 0.0
    exercise_counts: Counter = Counter()
    entries = []
    hearts, max_hearts = [], []
    calories = 0.0

    for r in recorded:
        d = plan_to_dict(r)
        volume += float(d["total_volume"] or 0)
        names = [i.exercise_name for i in (r.items or []) if i.exercise_name]
        for name in names:
            exercise_counts[name] += 1
        if r.avg_heart_rate:
            hearts.append(r.avg_heart_rate)
        if r.max_heart_rate:
            max_hearts.append(r.max_heart_rate)
        if r.calories is not None:
            calories += float(r.calories)
        entries.append(
            {
                "date": r.date.isoformat(),
                "status": "recorded",
                "summary": " · ".join(names[:3]) or "训练记录",
                "minutes": int(_fitness_minutes(r)),
                "volume": round(float(d["total_volume"] or 0), 1),
            }
        )
    for r in [x for x in rows if x.status == TR_STATUS_PLANNED]:
        names = [i.exercise_name for i in (r.items or []) if i.exercise_name]
        entries.append(
            {
                "date": r.date.isoformat(),
                "status": "planned",
                "summary": " · ".join(names[:3]) or (r.remark or "训练计划"),
                "minutes": 0,
                "volume": 0,
            }
        )

    top = [
        {"name": name, "count": count}
        for name, count in sorted(exercise_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    ]
    return {
        "plans": plans,
        "records": len(recorded),
        "minutes": int(minutes),
        "volume": round(volume, 1),
        "calories": round(calories, 1),
        "avg_heart_rate": round(sum(hearts) / len(hearts)) if hearts else None,
        "max_heart_rate": max(max_hearts) if max_hearts else None,
        "top_exercises": top,
        "entries": entries,
    }


def _swim_facts(rows: list) -> dict:
    recorded = [r for r in rows if r.status != TR_STATUS_PLANNED]
    plans = len(rows) - len(recorded)
    distance = sum((r.distance_m or 0) for r in recorded)
    duration_s = sum((r.duration_s or 0) for r in recorded)
    weighted_pace = calc_pace(duration_s, distance)
    paces = [p for r in recorded if (p := calc_pace(r.duration_s or 0, r.distance_m or 0)) is not None]
    hearts = [r.avg_heart_rate for r in recorded if r.avg_heart_rate]
    calories = sum(float(r.calories) if r.calories is not None else 0 for r in recorded)
    strokes: Counter = Counter()
    entries = []
    for r in recorded:
        if r.main_stroke:
            strokes[SWIM_STROKE_LABELS.get(r.main_stroke, r.main_stroke)] += 1
        d = swim_to_dict(r)
        parts = []
        if r.distance_m:
            parts.append(f"{r.distance_m}m")
        if r.duration_s:
            parts.append(_duration_text(r.duration_s))
        if d.get("pace"):
            parts.append(f"{d['pace']}/100m")
        entries.append(
            {
                "date": r.date.isoformat(),
                "status": "recorded",
                "summary": " · ".join(parts) or "游泳记录",
                "distance_m": r.distance_m,
                "duration_s": r.duration_s,
                "pace": d.get("pace"),
            }
        )
    for r in [x for x in rows if x.status == TR_STATUS_PLANNED]:
        d = swim_to_dict(r)
        entries.append(
            {
                "date": r.date.isoformat(),
                "status": "planned",
                "summary": r.remark or "游泳计划",
                "distance_m": r.distance_m,
                "duration_s": r.duration_s,
                "pace": d.get("pace"),
            }
        )
    return {
        "plans": plans,
        "records": len(recorded),
        "distance_m": int(distance),
        "duration_s": int(duration_s),
        "minutes": int(duration_s // 60),
        "weighted_pace": weighted_pace,
        "best_pace": min(paces) if paces else None,
        "worst_pace": max(paces) if paces else None,
        "avg_heart_rate": round(sum(hearts) / len(hearts)) if hearts else None,
        "calories": round(calories, 1),
        "stroke_counts": dict(strokes),
        "entries": entries,
    }


def _dance_facts(rows: list) -> dict:
    recorded = [r for r in rows if r.status != TR_STATUS_PLANNED]
    plans = len(rows) - len(recorded)
    duration_s = sum((r.duration_s or 0) for r in recorded)
    stars = [r.stars for r in recorded if r.stars is not None]
    calories = sum(float(r.calories) if r.calories is not None else 0 for r in recorded)
    types: Counter = Counter()
    teachers: Counter = Counter()
    entries = []
    for r in recorded:
        if r.dance_type:
            types[r.dance_type] += 1
        if r.teacher:
            teachers[r.teacher] += 1
        parts = [r.dance_type or "舞蹈"]
        if r.teacher:
            parts.append(r.teacher)
        if r.stars:
            parts.append(f"★{r.stars}")
        if r.duration_s:
            parts.append(_duration_text(r.duration_s))
        entries.append(
            {
                "date": r.date.isoformat(),
                "status": "recorded",
                "summary": " · ".join(parts),
                "stars": r.stars,
                "duration_s": r.duration_s,
            }
        )
    for r in [x for x in rows if x.status == TR_STATUS_PLANNED]:
        entries.append(
            {
                "date": r.date.isoformat(),
                "status": "planned",
                "summary": " · ".join([x for x in (r.dance_type, r.teacher, r.remark) if x]) or "舞蹈计划",
                "stars": r.stars,
                "duration_s": r.duration_s,
            }
        )
    return {
        "plans": plans,
        "records": len(recorded),
        "minutes": int(duration_s // 60),
        "duration_s": int(duration_s),
        "avg_stars": round(sum(stars) / len(stars), 1) if stars else None,
        "calories": round(calories, 1),
        "types": dict(types),
        "teachers": dict(teachers),
        "entries": entries,
    }


# ---------- 身体 ----------
def _body_facts(db: Session, user_id: int, period: Period) -> dict:
    out = {}
    for key, label, unit in BODY_METRICS:
        day_map = body_service.normalize_day_values(db, user_id, key)
        baseline = None
        latest = None
        measured = 0
        for d, v in sorted((d, v) for d, v in day_map.items() if v is not None):
            if d < period.start:
                baseline = v
            elif d <= period.as_of:
                latest = v
                measured += 1
        change = round(latest - baseline, 2) if baseline is not None and latest is not None else None
        out[key] = {
            "label": label,
            "unit": unit,
            "baseline": baseline,
            "latest": latest,
            "change": change,
            "measured_count": measured,
        }
    return out


# ---------- 状态记录 ----------
def _state_facts(db: Session, user_id: int, start: date, end: date) -> dict:
    types = {}
    pain_days = 0
    mood_low_days = 0
    for t in STATE_TYPES:
        model = STATE_MODELS[t]
        rows = (
            db.query(model)
            .filter(model.user_id == user_id, model.date >= start, model.date <= end)
            .all()
        )
        rated = [r.star for r in rows if r.star is not None]
        types[t] = {
            "label": STATE_TYPE_LABELS[t],
            "days": len(rows),
            "rated_days": len(rated),
            "avg": round(sum(rated) / len(rated), 1) if rated else None,
        }
        if t == "myalgia":
            pain_days = sum(1 for r in rows if r.star is not None and r.star >= 2)
        if t == "mood":
            mood_low_days = sum(1 for r in rows if r.star is not None and r.star <= 2)
    return {"types": types, "pain_days": pain_days, "mood_low_days": mood_low_days}


# ---------- 生理周期 ----------
def _cycle_facts(db: Session, user, days: list[date], workouts_by_day: dict) -> dict | None:
    """只对女性且存在月经记录生成；真实/推算/预测分开统计。"""
    if user.gender == "男" or not days:
        return None
    months = sorted({(d.year, d.month) for d in days})
    day_map: dict[str, dict] = {}
    has_records = False
    for year, month in months:
        cal = cycle_service.calendar_month(db, user.id, year, month)
        has_records = has_records or bool(cal["overview"]["has_records"])
        for item in cal["days"]:
            day_map[item["date"]] = item
    if not has_records:
        return None

    phase_days: Counter = Counter()
    phase_group_days: Counter = Counter()
    source_days: Counter = Counter()
    period_state_days: Counter = Counter()
    sport_levels: Counter = Counter()
    pain_days = 0
    phase_workouts: dict[str, dict] = {}

    for d in days:
        item = day_map.get(d.isoformat())
        if not item:
            continue
        phase = item.get("phase_key")
        if phase:
            phase_days[phase] += 1
            group = PHASE_GROUP_MAP.get(phase)
            if group:
                phase_group_days[group] += 1
            source_days[item.get("phase_source") or "derived"] += 1
        if item.get("period_state"):
            period_state_days[item["period_state"]] += 1
        if item.get("sport_level"):
            sport_levels[item["sport_level"]] += 1
        if (item.get("pain_level") or 0) >= 2:
            pain_days += 1
        records, minutes = workouts_by_day.get(d, (0, 0))
        if phase and records:
            bucket = phase_workouts.setdefault(
                phase,
                {"key": phase, "label": PHASE_LABELS.get(phase, phase), "records": 0, "minutes": 0},
            )
            bucket["records"] += records
            bucket["minutes"] += minutes

    periods = cycle_service.list_periods(db, user.id)
    latest_cycle_length = next((p["cycle_length"] for p in periods if p.get("cycle_length")), None)
    return {
        "phase_days": {PHASE_LABELS[k]: v for k, v in phase_days.items()},
        "phase_groups": {PHASE_GROUP_LABELS[k]: v for k, v in phase_group_days.items()},
        "source_days": {("真实记录" if k == "recorded" else "预测" if k == "predicted" else "推算"): v
                        for k, v in source_days.items()},
        "period_state_days": {PERIOD_STATE_LABELS.get(k, k): v for k, v in period_state_days.items()},
        "sport_levels": {SPORT_LEVEL_LABELS.get(k, k): v for k, v in sport_levels.items()},
        "pain_days": pain_days,
        "phase_workouts": [
            v for v in sorted(phase_workouts.values(), key=lambda x: -x["records"])
        ],
        "latest_cycle_length": latest_cycle_length,
    }


# ---------- 心得 ----------
def _notes(rows: dict, limit: int) -> list[dict]:
    items = []
    for r in rows["fitness"]:
        if r.status == TR_STATUS_PLANNED:
            continue
        texts = []
        if r.note:
            texts.extend(x for x in (r.note.best_movement, r.note.notes, r.note.next_steps) if x)
        if r.remark:
            texts.append(r.remark)
        for text in texts:
            items.append({"date": r.date.isoformat(), "sport": "健身", "text": str(text)[:120]})
    for r in rows["swim"]:
        if r.status == TR_STATUS_PLANNED:
            continue
        texts = []
        if r.note and r.note.stroke_insight:
            texts.append(r.note.stroke_insight)
        if r.note and r.note.notes:
            texts.append(r.note.notes)
        if r.remark:
            texts.append(r.remark)
        for text in texts:
            items.append({"date": r.date.isoformat(), "sport": "游泳", "text": str(text)[:120]})
    for r in rows["dance"]:
        if r.status == TR_STATUS_PLANNED:
            continue
        texts = []
        if r.note and r.note.notes:
            texts.append(r.note.notes)
        if r.remark:
            texts.append(r.remark)
        for text in texts:
            items.append({"date": r.date.isoformat(), "sport": "舞蹈", "text": str(text)[:120]})
    return items[:limit]


# ---------- 周节奏（月报） ----------
def _week_breakdown(per_day: dict, period: Period) -> list[dict]:
    buckets = []
    s = monday_of(period.start)
    index = 1
    while s <= period.as_of:
        ws = max(s, period.start)
        we = min(s + timedelta(days=6), period.as_of)
        records = sum(per_day.get(ws + timedelta(days=i), {}).get("records", 0) for i in range((we - ws).days + 1))
        minutes = sum(per_day.get(ws + timedelta(days=i), {}).get("minutes", 0) for i in range((we - ws).days + 1))
        active = sum(1 for i in range((we - ws).days + 1)
                     if per_day.get(ws + timedelta(days=i), {}).get("records", 0) > 0)
        buckets.append(
            {
                "label": f"第{index}周",
                "start": ws.isoformat(),
                "end": we.isoformat(),
                "records": records,
                "minutes": int(minutes),
                "active_days": active,
            }
        )
        s = s + timedelta(days=7)
        index += 1
    return buckets


def _runs(days: list[date], per_day: dict) -> tuple[int, int]:
    """最长连续运动天数、最长连续无记录天数。"""
    longest_active = longest_idle = 0
    cur_active = cur_idle = 0
    for d in days:
        if per_day.get(d, {}).get("records", 0) > 0:
            cur_active += 1
            cur_idle = 0
            longest_active = max(longest_active, cur_active)
        else:
            cur_idle += 1
            cur_active = 0
            longest_idle = max(longest_idle, cur_idle)
    return longest_active, longest_idle


# ---------- 组装 ----------
def build_facts(db: Session, user, period: Period) -> dict:
    """构建一个周期的完整事实快照；同一份数据同时供页面卡片与模型叙事使用。"""
    days = period_days(period)
    rows = _sport_rows(db, user.id, period.start, period.as_of)
    totals = _totals(rows)
    prev_end = period.start - timedelta(days=1)
    if period.type == REPORT_WEEKLY:
        prev_start = period.start - timedelta(days=7)
    else:
        prev_start = prev_end.replace(day=1)
    if period.partial:
        # 进行中周期只对比上期「同期」天数，避免 17 天 vs 整月造成假涨跌
        elapsed = (period.as_of - period.start).days
        prev_end = min(prev_end, prev_start + timedelta(days=elapsed))
    prev_totals = _totals(_sport_rows(db, user.id, prev_start, prev_end))

    per_day: dict[date, dict] = {}
    for d in days:
        per_day[d] = {"records": 0, "minutes": 0}
    workouts_by_day: dict[date, tuple[int, int]] = {}
    for r in rows["fitness"]:
        if r.status == TR_STATUS_PLANNED:
            continue
        per_day.setdefault(r.date, {"records": 0, "minutes": 0})["records"] += 1
        per_day[r.date]["minutes"] += _fitness_minutes(r)
    for key in ("swim", "dance"):
        for r in rows[key]:
            if r.status == TR_STATUS_PLANNED:
                continue
            per_day.setdefault(r.date, {"records": 0, "minutes": 0})["records"] += 1
            if r.duration_s:
                per_day[r.date]["minutes"] += r.duration_s // 60
    for d, item in per_day.items():
        workouts_by_day[d] = (item["records"], item["minutes"])

    fitness = _fitness_facts(rows["fitness"])
    swim = _swim_facts(rows["swim"])
    dance = _dance_facts(rows["dance"])
    body = _body_facts(db, user.id, period)
    state = _state_facts(db, user.id, period.start, period.as_of)
    cycle = _cycle_facts(db, user, days, workouts_by_day)

    completeness = {
        "days": len(days),
        "recorded_days": len(totals["active_dates"]),
        "no_record_dates": sorted(d.isoformat() for d in days if per_day.get(d, {}).get("records", 0) == 0),
        "has_any_record": totals["records"] > 0,
    }
    missing = []
    if fitness["records"] and not fitness["avg_heart_rate"]:
        missing.append("健身平均心率")
    if swim["records"] and not swim["distance_m"]:
        missing.append("游泳距离")
    if (swim["records"] or dance["records"]) and not totals["kcal"]:
        missing.append("热量")
    if not body["weight"]["measured_count"]:
        missing.append("体重实测")
    if not body["body_fat"]["measured_count"]:
        missing.append("体脂实测")
    if not any(v["days"] for v in state["types"].values()):
        missing.append("状态记录")
    completeness["missing"] = missing

    metrics = {}
    prev_tag = "同期" if period.partial else ""
    for key, label, value, unit in (
        ("total.records", "运动次数", totals["records"], "次"),
        ("total.plans", "计划条数", totals["plans"], "条"),
        ("total.minutes", "运动时长", totals["minutes"], "分钟"),
        ("total.active_days", "活跃天数", totals["active_days"], "天"),
        ("total.kcal", "运动热量", totals["kcal"], "千卡"),
        ("prev.records", f"上期{prev_tag}运动次数", prev_totals["records"], "次"),
        ("prev.minutes", f"上期{prev_tag}运动时长", prev_totals["minutes"], "分钟"),
        ("prev.active_days", f"上期{prev_tag}活跃天数", prev_totals["active_days"], "天"),
        ("prev.kcal", f"上期{prev_tag}运动热量", prev_totals["kcal"], "千卡"),
    ):
        metrics[key] = _metric(key, label, value, unit)
    compare_label = ("较上周" if period.type == REPORT_WEEKLY else "较上月") + prev_tag
    for key in ("records", "minutes", "kcal", "active_days"):
        delta = totals[key] - prev_totals[key]
        metrics[f"delta.{key}"] = _metric(
            f"delta.{key}",
            f"{compare_label}变化",
            _num(delta),
            "次" if key == "records" else "分钟" if key == "minutes" else "千卡" if key == "kcal" else "天",
        )

    for key, label, value, unit in (
        ("fitness.records", "健身次数", fitness["records"], "次"),
        ("fitness.plans", "健身计划", fitness["plans"], "条"),
        ("fitness.minutes", "健身时长", fitness["minutes"], "分钟"),
        ("fitness.volume", "健身容量", fitness["volume"], None),
        ("fitness.avg_hr", "健身平均心率", fitness["avg_heart_rate"], "bpm"),
        ("fitness.max_hr", "健身最高心率", fitness["max_heart_rate"], "bpm"),
        ("swim.records", "游泳次数", swim["records"], "次"),
        ("swim.distance_m", "游泳距离", swim["distance_m"], "米"),
        ("swim.minutes", "游泳时长", swim["minutes"], "分钟"),
        ("swim.weighted_pace", "游泳加权配速", swim["weighted_pace"], "分/100米"),
        ("swim.best_pace", "游泳最好配速", swim["best_pace"], "分/100米"),
        ("swim.worst_pace", "游泳最差配速", swim["worst_pace"], "分/100米"),
        ("dance.records", "舞蹈课次", dance["records"], "次"),
        ("dance.minutes", "舞蹈时长", dance["minutes"], "分钟"),
        ("dance.avg_stars", "舞蹈平均评分", dance["avg_stars"], "星"),
    ):
        metrics[key] = _metric(key, label, value, unit)
    metrics["fitness.top_exercise"] = _metric(
        "fitness.top_exercise", "最常练动作",
        fitness["top_exercises"][0]["name"] if fitness["top_exercises"] else None,
    )

    for key, label, unit in BODY_METRICS:
        item = body[key]
        metrics[f"body.{key}.latest"] = _metric(f"body.{key}.latest", f"{label}最新", item["latest"], unit)
        metrics[f"body.{key}.change"] = _metric(f"body.{key}.change", f"{label}变化", item["change"], unit)

    for t, item in state["types"].items():
        metrics[f"state.{t}.avg"] = _metric(f"state.{t}.avg", f"{item['label']}均分", item["avg"], "星")
        metrics[f"state.{t}.days"] = _metric(f"state.{t}.days", f"{item['label']}记录天数", item["days"], "天")
    metrics["state.pain_days"] = _metric("state.pain_days", "肌肉疼痛≥2的天数", state["pain_days"], "天")
    metrics["state.mood_low_days"] = _metric("state.mood_low_days", "情绪≤2的天数", state["mood_low_days"], "天")

    weekly_breakdown = []
    strongest = weakest = None
    longest_active = longest_idle = 0
    if period.type == REPORT_MONTHLY:
        weekly_breakdown = _week_breakdown(per_day, period)
        active_weeks = [w for w in weekly_breakdown if w["records"] > 0]
        if active_weeks:
            strongest = max(active_weeks, key=lambda w: (w["minutes"], w["records"]))
            weakest = min(active_weeks, key=lambda w: (w["minutes"], w["records"]))
        longest_active, longest_idle = _runs(days, per_day)

    if cycle:
        menses = cycle["phase_groups"].get("经期", 0)
        foll = cycle["phase_groups"].get("卵泡期/排卵", 0)
        luteal = cycle["phase_groups"].get("黄体期", 0)
        for key, label, value in (
            ("cycle.menses_days", "经期天数", menses),
            ("cycle.follicular_days", "卵泡期/排卵天数", foll),
            ("cycle.luteal_days", "黄体期天数", luteal),
            ("cycle.pain_days", "周期疼痛≥2的天数", cycle["pain_days"]),
            ("cycle.period_days", "经期相关天数", sum(cycle["period_state_days"].values())),
        ):
            metrics[key] = _metric(key, label, value, "天")

    if period.type == REPORT_MONTHLY:
        metrics["month.longest_streak"] = _metric("month.longest_streak", "最长连续运动", longest_active, "天")
        metrics["month.longest_gap"] = _metric("month.longest_gap", "最长空档", longest_idle, "天")
        metrics["month.strongest_week"] = _metric(
            "month.strongest_week", "最活跃的一周", strongest["label"] if strongest else None
        )
        metrics["month.weakest_week"] = _metric(
            "month.weakest_week", "最不活跃的一周", weakest["label"] if weakest else None
        )

    cards = []
    for key, label, unit in (
        ("records", "运动次数", "次"),
        ("minutes", "运动时长", "分钟"),
        ("active_days", "活跃天数", "天"),
        ("kcal", "运动热量", "千卡"),
    ):
        delta = totals[key] - prev_totals[key]
        cards.append(
            {
                "key": key,
                "label": label,
                "value": _num(totals[key]),
                "unit": unit,
                "display": _display(totals[key]),
                "delta_text": f"{compare_label} {'+' if delta > 0 else ''}{_fmt(delta)}",
                "delta_dir": "up" if delta > 0 else "down" if delta < 0 else "flat",
            }
        )

    facts = {
        "period_type": period.type,
        "period_start": period.start.isoformat(),
        "period_end": period.end.isoformat(),
        "as_of": period.as_of.isoformat(),
        "partial": period.partial,
        "label": period.label,
        "range_label": period.range_label,
        "metrics": metrics,
        "cards": cards,
        "totals": {
            "records": totals["records"],
            "plans": totals["plans"],
            "minutes": totals["minutes"],
            "kcal": totals["kcal"],
            "active_days": totals["active_days"],
        },
        "prev_totals": {
            "records": prev_totals["records"],
            "plans": prev_totals["plans"],
            "minutes": prev_totals["minutes"],
            "kcal": prev_totals["kcal"],
            "active_days": prev_totals["active_days"],
        },
        "sports": {"fitness": fitness, "swim": swim, "dance": dance},
        "body": body,
        "state": state,
        "cycle": cycle,
        "weekly_breakdown": weekly_breakdown,
        "notes": _notes(rows, 8 if period.type == REPORT_MONTHLY else 5),
        "completeness": completeness,
        "kcal_scope": "swim_dance",
        "kcal_note": "总热量仅汇总游泳与舞蹈；健身热量单独展示，不计入总热量。",
    }
    return facts
