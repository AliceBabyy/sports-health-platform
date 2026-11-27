"""每日训练建议事实层：只读、确定性计算，复用既有 service 口径。

事实只描述「已经发生的记录」和「当天已存在的计划」，不做任何模型推断；
模型只负责在既定事实与硬约束内做取舍与解释。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.constants import (
    PHASE_LABELS,
    SEGMENT_CURRENT,
    SEGMENT_INFERRED,
    SEGMENT_PREDICTED,
    SEGMENT_RECORDED,
    SPORT_AVERAGE,
    SPORT_LABELS,
    SPORT_REST,
    TR_STATUS_PLANNED,
    TR_STATUS_RECORDED,
    today_local,
)
from app.modules.state_record.models import STATE_TYPE_LABELS, STATE_TYPES
from app.modules.body import service as body_service
from app.modules.cycle import service as cycle_service
from app.modules.cycle.models import PeriodLog, PeriodRecord
from app.modules.dance import service as dance_service
from app.modules.dance.models import DanceRecord
from app.modules.overview.service import fitness_minutes
from app.modules.profile import service as profile_service
from app.modules.state_record import service as state_service
from app.modules.swim import service as swim_service
from app.modules.swim.models import SwimRecord
from app.modules.training import service as training_service
from app.modules.training.models import TrainingRecord

# ---------- 硬约束阈值（模块内常量，不进 .env：只有一处口径） ----------
PAIN_HIGH_STAR = 2            # 经期疼痛 ≥2 → 强度封顶「低」且不留力量部位；单纯肌肉酸痛不触发
INFLAMMATION_HIGH_STAR = 4    # 今日炎症 ≥4（明显）→ 强度封顶「低」
INFLAMMATION_MID_STAR = 3     # 今日炎症 ≥3（偏重）→ 强度封顶「中」；0~2 不因炎症降档
RECOVERY_LOW_STAR = 1         # 今日恢复 ≤1 → 强度封顶「低」
RECOVERY_FAIR_STAR = 2        # 今日恢复 2 → 强度封顶「中」
MOOD_LOW_STAR = 1             # 今日情绪 ≤1 → 强度封顶「中」
HEAVY_VOLUME = 5000.0         # 昨日健身容量 ≥5000 → 强度封顶「中」
VERY_HEAVY_VOLUME = 8000.0    # 昨日健身容量 ≥8000 → 强度封顶「低」
HEAVY_MINUTES = 90            # 昨日运动总时长 ≥90 分钟 → 强度封顶「中」
VERY_HEAVY_MINUTES = 120      # 昨日运动总时长 ≥120 分钟 → 强度封顶「低」
WEIGHT_WINDOW_DAYS = 30       # 体重变化窗口
RECENT_WEEKS_DAYS = 7
RECENT_TYPE_WINDOW_DAYS = 30  # 近 30 天运动类型偏好窗口

SOURCE_LABELS = {
    SEGMENT_RECORDED: "真实记录",
    SEGMENT_CURRENT: "当前段（按最近一次记录推算）",
    SEGMENT_INFERRED: "漏记补推",
    SEGMENT_PREDICTED: "预测",
}

BODY_FACT_KEYS = ("weight", "body_fat", "waist", "hip")


# ---------- 小工具 ----------
def _num(value, digits: int = 1):
    if value is None:
        return None
    if isinstance(value, Decimal):
        value = float(value)
    return round(value, digits)


def _minutes_from_seconds(seconds) -> int:
    return int(seconds) // 60 if seconds else 0


def _fitness_entry(row: TrainingRecord) -> dict:
    data = training_service.plan_to_dict(row) or {}
    return {
        "id": row.id,
        "status": row.status,
        "minutes": fitness_minutes(row),
        "avg_heart_rate": row.avg_heart_rate,
        "calories": _num(row.calories),
        "volume": data.get("total_volume", 0.0),
        "body_parts": data.get("body_parts_summary", ""),
        "items": [
            {
                "name": item.get("exercise_name"),
                "part": item.get("body_part"),
                "sets": item.get("sets"),
                "reps": item.get("reps"),
                "weight_kg": item.get("weight_kg"),
            }
            for item in (data.get("items") or [])[:10]
        ],
        "item_count": data.get("item_count", 0),
    }


def _swim_entry(row: SwimRecord) -> dict:
    data = swim_service.to_dict(row)
    return {
        "id": row.id,
        "status": row.status,
        "distance_m": data.get("distance_m"),
        "minutes": _minutes_from_seconds(row.duration_s),
        "pace": data.get("pace"),
        "stroke": data.get("main_stroke_label"),
        "avg_heart_rate": data.get("avg_heart_rate"),
        "calories": data.get("calories"),
    }


def _dance_entry(row: DanceRecord) -> dict:
    data = dance_service.to_dict(row)
    return {
        "id": row.id,
        "status": row.status,
        "dance_type": data.get("dance_type"),
        "teacher": data.get("teacher"),
        "stars": data.get("stars"),
        "minutes": _minutes_from_seconds(row.duration_s),
    }


def _day_block(db: Session, user_id: int, day: date) -> dict:
    """单日三运动：记录（recorded）与计划（planned）分开统计。"""
    rows = {
        "fitness": db.query(TrainingRecord)
        .filter(TrainingRecord.user_id == user_id, TrainingRecord.date == day)
        .order_by(TrainingRecord.id)
        .all(),
        "swim": db.query(SwimRecord)
        .filter(SwimRecord.user_id == user_id, SwimRecord.date == day)
        .order_by(SwimRecord.id)
        .all(),
        "dance": db.query(DanceRecord)
        .filter(DanceRecord.user_id == user_id, DanceRecord.date == day)
        .order_by(DanceRecord.id)
        .all(),
    }
    records = {"fitness": [], "swim": [], "dance": []}
    plans = {"fitness": [], "swim": [], "dance": []}
    totals = {"records": 0, "minutes": 0, "volume": 0.0, "kcal": 0.0}
    for row in rows["fitness"]:
        entry = _fitness_entry(row)
        if row.status == TR_STATUS_PLANNED:
            plans["fitness"].append(entry)
        else:
            records["fitness"].append(entry)
    for key, model_rows, entry_fn in (
        ("swim", rows["swim"], _swim_entry),
        ("dance", rows["dance"], _dance_entry),
    ):
        for row in model_rows:
            entry = entry_fn(row)
            if row.status == TR_STATUS_PLANNED:
                plans[key].append(entry)
            else:
                records[key].append(entry)

    for key in ("fitness", "swim", "dance"):
        for entry in records[key]:
            totals["records"] += 1
            totals["minutes"] += entry.get("minutes") or 0
            if key == "fitness":
                totals["volume"] += entry.get("volume") or 0.0
            else:
                totals["kcal"] += entry.get("calories") or 0.0
    totals["volume"] = round(totals["volume"], 1)
    totals["kcal"] = round(totals["kcal"], 1)
    return {"date": day.isoformat(), "records": records, "plans": plans, "totals": totals}


def _body_block(db: Session, user_id: int, day: date) -> dict:
    snap = body_service.latest_snapshot(db, user_id)
    block: dict = {}
    for key in BODY_FACT_KEYS:
        item = snap.get(key) or {}
        value = _num(item.get("value"))
        block[key] = {
            "label": {"weight": "体重", "body_fat": "体脂率", "waist": "腰围", "hip": "臀围"}[key],
            "value": value,
            "record_date": item.get("record_date"),
            "delta_vs_prev": item.get("delta"),
        }
    block["bmi"] = _num(snap.get("bmi"))
    block["bmi_state"] = snap.get("bmi_state")
    block["latest_date"] = (snap.get("latest_dates") or {}).get("basic")

    day_map = body_service.normalize_day_values(db, user_id, "weight")
    window_start = day - timedelta(days=WEIGHT_WINDOW_DAYS)
    points = sorted(
        (d, v) for d, v in day_map.items() if v is not None and d >= window_start
    )
    block["weight_change_30d"] = (
        round(points[-1][1] - points[0][1], 2) if len(points) >= 2 else None
    )
    return block


def _recent_block(db: Session, user_id: int, day: date) -> dict:
    """近 3 / 7 / 30 天负荷：近 7 天含部位分布，近 30 天含运动类型次数（用于推荐运动类型）。"""
    start7 = day - timedelta(days=RECENT_WEEKS_DAYS - 1)
    start30 = day - timedelta(days=RECENT_TYPE_WINDOW_DAYS - 1)
    rows = {
        "fitness": db.query(TrainingRecord)
        .filter(
            TrainingRecord.user_id == user_id,
            TrainingRecord.date >= start30,
            TrainingRecord.date <= day,
        )
        .all(),
        "swim": db.query(SwimRecord)
        .filter(SwimRecord.user_id == user_id, SwimRecord.date >= start30, SwimRecord.date <= day)
        .all(),
        "dance": db.query(DanceRecord)
        .filter(DanceRecord.user_id == user_id, DanceRecord.date >= start30, DanceRecord.date <= day)
        .all(),
    }
    start3 = day - timedelta(days=2)
    start2 = day - timedelta(days=1)
    window7 = {"records": 0, "minutes": 0, "volume": 0.0}
    window3 = {"records": 0, "minutes": 0, "volume": 0.0}
    window30 = {"records": 0, "fitness": 0, "swim": 0, "dance": 0}
    body_parts: dict[str, int] = {}
    parts_2d: dict[str, int] = {}

    for row in rows["fitness"]:
        if row.status != TR_STATUS_RECORDED:
            continue
        window30["records"] += 1
        window30["fitness"] += 1
        if row.date < start7:
            continue
        minutes = fitness_minutes(row)
        volume = (_fitness_entry(row).get("volume") or 0.0)
        window7["records"] += 1
        window7["minutes"] += minutes
        window7["volume"] += volume
        if row.date >= start3:
            window3["records"] += 1
            window3["minutes"] += minutes
            window3["volume"] += volume
        for item in row.items or []:
            if not item.body_part:
                continue
            body_parts[item.body_part] = body_parts.get(item.body_part, 0) + 1
            if row.date >= start2:  # 昨天与今天练过的部位，今天不再练
                parts_2d[item.body_part] = parts_2d.get(item.body_part, 0) + 1

    for key in ("swim", "dance"):
        for row in rows[key]:
            if row.status != TR_STATUS_RECORDED:
                continue
            window30["records"] += 1
            window30[key] += 1
            if row.date < start7:
                continue
            minutes = _minutes_from_seconds(row.duration_s)
            window7["records"] += 1
            window7["minutes"] += minutes
            if row.date >= start3:
                window3["records"] += 1
                window3["minutes"] += minutes

    window7["volume"] = round(window7["volume"], 1)
    window3["volume"] = round(window3["volume"], 1)
    window7["days"] = RECENT_WEEKS_DAYS
    window3["days"] = 3
    window30["days"] = RECENT_TYPE_WINDOW_DAYS

    last = (
        db.query(TrainingRecord)
        .filter(
            TrainingRecord.user_id == user_id,
            TrainingRecord.status == TR_STATUS_RECORDED,
            TrainingRecord.date <= day,
        )
        .order_by(TrainingRecord.date.desc(), TrainingRecord.id.desc())
        .first()
    )
    ref = datetime.combine(day, datetime.min.time())
    since = {
        "days": (day - last.date).days if last else None,
        "hours": (
            round((ref - last.end_time).total_seconds() / 3600, 1)
            if last and last.end_time and last.end_time <= ref
            else None
        ),
    }

    return {
        "window_3d": window3,
        "window_7d": window7,
        "window_30d": window30,
        "body_part_counts": dict(sorted(body_parts.items(), key=lambda kv: -kv[1])),
        "recent_parts_2d": sorted(parts_2d, key=lambda part: -parts_2d[part]),
        "since_last_fitness": since,
    }


def _state_block(db: Session, user_id: int, day: date) -> dict:
    """今天 / 昨天 / 近 3 天的各记录项状态（星级 + 备注）。"""
    days = [day, day - timedelta(days=1), day - timedelta(days=2)]
    by_date = {d: state_service.get_by_date(db, user_id, d) for d in days}

    def brief(record):
        if not record:
            return {"star": None, "remark": None}
        return {"star": record.get("star"), "remark": record.get("remark")}

    today_block = {t: brief(by_date[day].get(t)) for t in STATE_TYPES}
    yesterday_block = {t: brief(by_date[day - timedelta(days=1)].get(t)) for t in STATE_TYPES}
    avg3 = {}
    for t in STATE_TYPES:
        stars = [
            by_date[d][t]["star"]
            for d in days
            if by_date[d].get(t) and by_date[d][t].get("star") is not None
        ]
        avg3[t] = {
            "avg": round(sum(stars) / len(stars), 1) if stars else None,
            "rated_days": len(stars),
        }
    return {
        "labels": {t: STATE_TYPE_LABELS[t] for t in STATE_TYPES},
        "today": today_block,
        "yesterday": yesterday_block,
        "avg_3d": avg3,
    }


def _cycle_block(db: Session, user_id: int, gender: str | None, day: date) -> dict | None:
    """仅女性且存在月经记录时生成；真实 / 补推 / 预测分开标注。"""
    if gender == "男":
        return None
    if db.query(PeriodRecord.id).filter(PeriodRecord.user_id == user_id).first() is None:
        return None
    setting = cycle_service.get_settings(db, user_id)
    segments = cycle_service.build_segments(db, user_id, setting=setting, today=day)
    seg = cycle_service.segment_for_day(segments, day)
    if seg is None:
        return None
    cycle_day = (day - seg.start).days + 1
    phase = cycle_service.phase_in_segment(day, seg)
    log = db.query(PeriodLog).filter(PeriodLog.user_id == user_id, PeriodLog.log_date == day).first()
    pain = log.pain_level if log and log.pain_level is not None else None
    level = (
        cycle_service.sport_level_for(phase, cycle_day, seg.length, seg.period_length, pain or 0)
        if phase
        else None
    )
    return {
        "cycle_day": cycle_day,
        "segment_length": seg.length,
        "period_length": seg.period_length,
        "phase": PHASE_LABELS.get(phase),
        "sport_level_key": level,
        "sport_level": SPORT_LABELS.get(level),
        "pain_level": pain,
        "source": SOURCE_LABELS.get(seg.source, seg.source),
        "hormone_text": (
            cycle_service.hormone_text_for(phase, cycle_day, seg) if phase else None
        ),
    }


def _hard_limits(body: dict, yesterday: dict, recent: dict, state: dict, today: dict, cycle) -> list[dict]:
    """代码判定的硬约束：cap_verdict / cap_intensity 是上限，不是取值。

    权重口径：周期四档与恢复是主信号；炎症按明显程度降档；单纯肌肉酸痛不触发硬约束
    （只通过 recent_parts_2d 做部位避让，由提示词解释为正常训练反应）。
    """
    limits: list[dict] = []

    def add(key: str, label: str, cap_verdict: str | None = None,
            cap_intensity: str | None = None, block_parts: bool = False) -> None:
        limits.append(
            {
                "key": key,
                "label": label,
                "cap_verdict": cap_verdict,
                "cap_intensity": cap_intensity,
                "block_parts": block_parts,
            }
        )

    cycle_pain = (cycle or {}).get("pain_level")
    if cycle_pain is not None and cycle_pain >= PAIN_HIGH_STAR:
        add("cycle_pain_high", "经期疼痛偏重", cap_verdict="克制", cap_intensity="低", block_parts=True)

    if cycle:
        if cycle.get("sport_level_key") == SPORT_REST:
            add("cycle_rest", "周期状态建议休息", cap_verdict="克制", cap_intensity="低", block_parts=True)
        elif cycle.get("sport_level_key") == SPORT_AVERAGE:
            add("cycle_average", "周期状态一般", cap_intensity="中")

    inflammation = (state["today"].get("inflammation") or {}).get("star")
    if inflammation is not None and inflammation >= INFLAMMATION_HIGH_STAR:
        add("inflammation_high", "今日炎症明显", cap_intensity="低")
    elif inflammation is not None and inflammation >= INFLAMMATION_MID_STAR:
        add("inflammation_mid", "今日炎症偏重", cap_intensity="中")

    recovery = (state["today"].get("recovery") or {}).get("star")
    if recovery is not None and recovery <= RECOVERY_LOW_STAR:
        add("recovery_low", "今日恢复不足", cap_intensity="低")
    elif recovery is not None and recovery <= RECOVERY_FAIR_STAR:
        add("recovery_fair", "今日恢复一般", cap_intensity="中")

    minutes = yesterday["totals"]["minutes"]
    volume = yesterday["totals"]["volume"]
    if volume >= VERY_HEAVY_VOLUME or minutes >= VERY_HEAVY_MINUTES:
        add("yesterday_very_heavy", "昨日训练负荷很大", cap_verdict="克制", cap_intensity="低")
    elif volume >= HEAVY_VOLUME or minutes >= HEAVY_MINUTES:
        add("yesterday_heavy", "昨日训练负荷偏大", cap_intensity="中")

    has_today_strength = any(
        entry.get("item_count") for entry in today["records"]["fitness"]
    )
    if has_today_strength:
        add("trained_today", "今天已经练过力量", cap_verdict="克制", cap_intensity="低", block_parts=True)

    mood = (state["today"].get("mood") or {}).get("star")
    if mood is not None and mood <= MOOD_LOW_STAR:
        add("mood_low", "今日情绪偏低", cap_intensity="中")

    return limits


def _completeness(body, yesterday, recent, state, today, cycle) -> dict:
    has_body = body["weight"]["value"] is not None
    has_recent = recent["window_7d"]["records"] > 0
    has_state = any(
        (state["today"][t]["star"] is not None) or (state["yesterday"][t]["star"] is not None)
        for t in STATE_TYPES
    )
    has_any = has_body or has_recent or has_state

    missing = []
    if not has_state:
        missing.append("今天与昨天都没有状态记录")
    if not has_recent:
        missing.append("近 7 天没有运动记录")
    if body["weight"]["value"] is None:
        missing.append("没有体重实测")
    if body["body_fat"]["value"] is None:
        missing.append("没有体脂实测")
    if cycle is None:
        missing.append("无生理周期数据（男性或不适用）")

    return {
        "has_body": has_body,
        "has_recent_records": has_recent,
        "has_state_records": has_state,
        "has_any_record": has_any,
        "missing": missing,
        "note": "只统计 recorded 记录；plans_today 只是计划，不代表已完成。",
    }


def _health_profile_block(db: Session, user_id: int) -> list[dict]:
    """用户已保存的专项档案（每项最近一套，只返回有答案的题）。

    文本只作模型参考，不做结构化解析，也不参与 hard_limits 判定：
    安全边界由代码固定的记录事实决定，不靠模型理解自由文本。
    """
    from app.modules.profile.aspect_skills import skill_name
    from app.modules.profile.aspects import aspect_label
    from app.modules.profile.questionnaire import set_qa

    row = profile_service.get_health_profile(db, user_id)
    if row is None:
        return []
    result = []
    for question_set in row.sets:
        qa = [
            {
                "label": item["label"],
                "group": aspect_label(item["aspect"]),
                "answer": item["answer"],
            }
            for item in set_qa(question_set, answered_only=True)
        ]
        if not qa:
            continue
        generated_at = question_set.get("generated_at")
        result.append({
            "skill_key": question_set["skill_key"],
            "name": skill_name(question_set["skill_key"]),
            "generated_at": generated_at.isoformat() if generated_at else None,
            "qa": qa,
        })
    return result


def build_facts(db: Session, user, day: date | None = None) -> dict:
    """构建一天的事实快照；同一份数据同时供模型与回溯使用。"""
    day = day or today_local()
    gender = getattr(user, "gender", None)
    body = _body_block(db, user.id, day)
    yesterday = _day_block(db, user.id, day - timedelta(days=1))
    today = _day_block(db, user.id, day)
    recent = _recent_block(db, user.id, day)
    state = _state_block(db, user.id, day)
    cycle = _cycle_block(db, user.id, gender, day)
    return {
        "date": day.isoformat(),
        "profile": {
            "gender": gender,
            "age": getattr(user, "age", None),
            "health_profile": _health_profile_block(db, user.id),
        },
        "body": body,
        "yesterday": yesterday,
        "today_records": today["records"],
        "plans_today": today["plans"],
        "recent_load": recent,
        "state": state,
        "cycle": cycle,
        "hard_limits": _hard_limits(body, yesterday, recent, state, today, cycle),
        "completeness": _completeness(body, yesterday, recent, state, today, cycle),
    }
