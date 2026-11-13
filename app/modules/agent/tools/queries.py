"""Agent 只读查询：受控、按 user_id 隔离、返回结构化事实。

只做查询与结构化，不做任何写操作。口径复用各模块 service，保证数据问答与页面一致。
取数范围由调用方（模型按用户意图）决定：start / end 为 None 表示不限，即全部历史。

覆盖范围：身材（4 组）、状态记录（食欲/肌肉疼痛/炎症）、健身、游泳、舞蹈、
生理周期（参考值 + 月经记录 + 每日疼痛 + 今日阶段）、个人基本信息。
"""
from datetime import date

from sqlalchemy.orm import Session

from app.core.constants import (
    BODY_COLUMNS,
    BODY_KEYS,
    BODY_LABELS,
    BODY_UNITS,
    DEFAULT_CYCLE_LENGTH,
    DEFAULT_PERIOD_LENGTH,
    GROUP_LABELS,
    PHASE_LABELS,
    TR_STATUS_PLANNED,
    today_local,
)
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.body.service import GROUP_MODELS, all_group_rows
from app.modules.cycle import service as cycle_service
from app.modules.cycle.models import CycleSetting, DailyPainLog
from app.modules.dance.models import DanceRecord
from app.modules.dance.service import to_dict as dance_to_dict
from app.modules.overview.service import SPORT_LABELS, _fitness_minutes
from app.modules.state_record.models import STATE_MODELS, STATE_TYPES, STATE_TYPE_LABELS
from app.modules.state_record.service import to_dict as state_to_dict
from app.modules.swim.models import SwimRecord
from app.modules.swim.service import to_dict as swim_to_dict
from app.modules.training.models import TrainingRecord
from app.modules.training.service import plan_to_dict


SPORT_KEYS = ("fitness", "swim", "dance")
# 工具可暴露的身材指标白名单：全部 4 组字段（基础 / 期望 / 围度 / 目标）
BODY_METRIC_WHITELIST = tuple(BODY_KEYS)


def _range_dict(start: date | None, end: date | None) -> dict:
    """统一的取数范围描述：两端为 null 表示全部历史。"""
    return {
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "scope": "all" if start is None and end is None else "range",
    }


def _apply_date_range(query, date_column, start: date | None, end: date | None):
    if start is not None:
        query = query.filter(date_column >= start)
    if end is not None:
        query = query.filter(date_column <= end)
    return query


def _empty_stat() -> dict:
    return {"records": 0, "plans": 0, "minutes": 0, "kcal": 0.0}


def _assert_status(status: str) -> None:
    if status not in ("all", "planned", "recorded"):
        raise AppError(400, "status 取值不合法")


# ---------- 运动汇总（跨三类） ----------

def workout_summary(db: Session, user_id: int, start: date | None, end: date | None, sport: str) -> dict:
    """按范围统计已完成运动；start/end 为 None 时统计全部历史。"""
    if sport not in ("all", "fitness", "swim", "dance"):
        raise AppError(400, "运动类型不合法")
    stats = {k: _empty_stat() for k in SPORT_KEYS}
    active_days: set[date] = set()

    if sport in ("all", "fitness"):
        q = db.query(TrainingRecord).filter(TrainingRecord.user_id == user_id)
        q = _apply_date_range(q, TrainingRecord.date, start, end)
        for r in q.all():
            s = stats["fitness"]
            if r.status == TR_STATUS_PLANNED:
                s["plans"] += 1
            else:
                s["records"] += 1
                s["minutes"] += _fitness_minutes(r)
                active_days.add(r.date)

    for key, model in (("swim", SwimRecord), ("dance", DanceRecord)):
        if sport not in ("all", key):
            continue
        q = db.query(model).filter(model.user_id == user_id)
        q = _apply_date_range(q, model.date, start, end)
        for r in q.all():
            s = stats[key]
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
        "range": _range_dict(start, end),
        "sport_labels": SPORT_LABELS,
        "per_sport": stats,
        "total": total,
        "note": "时长与热量仅统计 recorded 记录，plans 单独计数；健身无热量字段。",
    }


# ---------- 健身明细 ----------

def fitness_records(
    db: Session,
    user_id: int,
    start: date | None,
    end: date | None,
    status: str = "all",
    limit: int | None = None,
) -> dict:
    """健身计划/记录明细（含动作与容量、练后心得）；不限范围即全量。"""
    _assert_status(status)
    q = db.query(TrainingRecord).filter(TrainingRecord.user_id == user_id)
    q = _apply_date_range(q, TrainingRecord.date, start, end)
    if status in ("planned", "recorded"):
        q = q.filter(TrainingRecord.status == status)
    q = q.order_by(TrainingRecord.date.desc(), TrainingRecord.id.desc())
    if limit is not None:
        q = q.limit(limit)

    records = []
    for row in q.all():
        item = plan_to_dict(row)
        item["status"] = str(item["status"])
        records.append(item)
    return {
        "range": _range_dict(start, end),
        "status": status,
        "limit": limit,
        "count": len(records),
        "records": records,
        "note": "status=recorded 才算完成；items 为动作明细，total_volume 为训练容量"
                 "（重量×组数×每组首个次数，缺项不计）；note 为练后心得。",
    }


# ---------- 游泳明细 ----------

def swim_records(
    db: Session,
    user_id: int,
    start: date | None,
    end: date | None,
    status: str = "all",
    limit: int | None = None,
) -> dict:
    """游泳计划/记录明细（距离、时长、配速、划频、泳姿、心得）；不限范围即全量。"""
    _assert_status(status)
    q = db.query(SwimRecord).filter(SwimRecord.user_id == user_id)
    q = _apply_date_range(q, SwimRecord.date, start, end)
    if status in ("planned", "recorded"):
        q = q.filter(SwimRecord.status == status)
    q = q.order_by(SwimRecord.date.desc(), SwimRecord.id.desc())
    if limit is not None:
        q = q.limit(limit)

    records = [swim_to_dict(row) for row in q.all()]
    for r in records:
        r["status"] = str(r["status"])
    return {
        "range": _range_dict(start, end),
        "status": status,
        "limit": limit,
        "count": len(records),
        "records": records,
        "note": "仅 status=recorded 计入完成；pace 单位 分钟/100 米，划频 次/分钟；"
                 "未手填划频时由总划水次数/时长派生。",
    }


# ---------- 舞蹈明细 ----------

def dance_records(
    db: Session,
    user_id: int,
    start: date | None,
    end: date | None,
    status: str = "all",
    limit: int | None = None,
) -> dict:
    """舞蹈计划/记录明细（舞种、老师、风格、时长、热量、心得）；不限范围即全量。"""
    _assert_status(status)
    q = db.query(DanceRecord).filter(DanceRecord.user_id == user_id)
    q = _apply_date_range(q, DanceRecord.date, start, end)
    if status in ("planned", "recorded"):
        q = q.filter(DanceRecord.status == status)
    q = q.order_by(DanceRecord.date.desc(), DanceRecord.id.desc())
    if limit is not None:
        q = q.limit(limit)

    records = [dance_to_dict(row) for row in q.all()]
    for r in records:
        r["status"] = str(r["status"])
    return {
        "range": _range_dict(start, end),
        "status": status,
        "limit": limit,
        "count": len(records),
        "records": records,
        "note": "status=recorded 才算完成；stars 为课程评分（1~5，可空）；note 为课后心得。",
    }


# ---------- 身材 ----------

def body_measurements(
    db: Session,
    user_id: int,
    metric: str,
    start: date | None,
    end: date | None,
) -> dict:
    """身材数据：metric=all 返回按日期合并的 4 组记录；指定指标返回该指标实测点序列。"""
    if metric == "all":
        return _body_all(db, user_id, start, end)
    if metric not in BODY_METRIC_WHITELIST:
        raise AppError(400, "不支持该身材指标")

    model = _model_for(metric)
    column = _column_for(metric)
    q = db.query(model.record_date, getattr(model, column)).filter(
        model.user_id == user_id,
        getattr(model, column).isnot(None),
    )
    q = _apply_date_range(q, model.record_date, start, end)
    rows = q.order_by(model.record_date.asc()).all()
    points = [{"date": d.isoformat(), "value": float(v)} for d, v in rows]
    return {
        "mode": "metric",
        "metric": metric,
        "label": BODY_LABELS[metric],
        "unit": BODY_UNITS[metric],
        "range": _range_dict(start, end),
        "sample_count": len(points),
        "points": points,
        "note": "点均为实际测量值，未测量日期不补沿用值；数据不足时不能据此判断趋势。",
    }


def _body_all(db: Session, user_id: int, start: date | None, end: date | None) -> dict:
    raw = all_group_rows(db, user_id, groups=("basic", "goal", "girth", "target"))
    merged: dict[date, dict] = {}
    for _group, rows in raw.items():
        for row in rows:
            record_date: date = row["record_date"]
            if start is not None and record_date < start:
                continue
            if end is not None and record_date > end:
                continue
            merged.setdefault(record_date, {}).update(row["values"])
    dates = sorted(merged.keys(), reverse=True)
    return {
        "mode": "all",
        "range": _range_dict(start, end),
        "count": len(dates),
        "groups": ["basic", "goal", "girth", "target"],
        "group_labels": GROUP_LABELS,
        "metric_labels": {k: BODY_LABELS[k] for k in BODY_KEYS},
        "metric_units": {k: BODY_UNITS[k] for k in BODY_KEYS},
        "rows": [{"date": d.isoformat(), "values": merged[d]} for d in dates],
        "note": "含基础 / 期望指标 / 围度 / 目标围度四组，同日四组合并一行；"
                 "只含实际录入值（沿用继承值按库内已存值展示），缺失字段不补值。",
    }


def _column_for(metric: str) -> str:
    return BODY_COLUMNS[metric]


def _model_for(metric: str):
    from app.core.constants import BODY_FIELDS

    return GROUP_MODELS[BODY_FIELDS[metric][3]]


# ---------- 状态记录 ----------

def state_records(
    db: Session,
    user_id: int,
    start: date | None,
    end: date | None,
    type_filter: str = "all",
    limit: int | None = None,
) -> dict:
    """状态记录（食欲 / 肌肉疼痛 / 炎症）跨表明细，按日期倒序；不限范围即全量。"""
    if type_filter != "all" and type_filter not in STATE_TYPES:
        raise AppError(400, "记录类型不合法")
    types = list(STATE_TYPES) if type_filter == "all" else [type_filter]
    records = []
    per_type: dict[str, int] = {t: 0 for t in STATE_TYPES}
    for t in types:
        model = STATE_MODELS[t]
        q = db.query(model).filter(model.user_id == user_id)
        q = _apply_date_range(q, model.date, start, end)
        rows = q.all()
        per_type[t] = len(rows)
        records.extend(state_to_dict(row, t) for row in rows)

    records.sort(key=lambda x: (x["date"], x["id"]), reverse=True)
    if limit is not None:
        records = records[:limit]
    return {
        "range": _range_dict(start, end),
        "type": type_filter,
        "type_labels": STATE_TYPE_LABELS,
        "limit": limit,
        "count": len(records),
        "per_type": per_type,
        "records": records,
        "note": "star 为 0~5 星，0=最低分、null=未评；三类各表同类同一天一行。",
    }


# ---------- 生理周期 ----------

def cycle_records(
    db: Session,
    user_id: int,
    start: date | None,
    end: date | None,
) -> dict:
    """生理周期数据：参考值 + 月经记录 + 每日疼痛 + 今日所在阶段（全部只读）。"""
    setting = db.get(CycleSetting, user_id)
    cycle_length = setting.cycle_length if setting else DEFAULT_CYCLE_LENGTH
    period_length = setting.period_length if setting else DEFAULT_PERIOD_LENGTH

    periods = cycle_service.list_periods(db, user_id)
    if start is not None:
        periods = [p for p in periods if date.fromisoformat(p["start_date"]) >= start]
    if end is not None:
        periods = [p for p in periods if date.fromisoformat(p["start_date"]) <= end]

    q = db.query(DailyPainLog).filter(DailyPainLog.user_id == user_id)
    q = _apply_date_range(q, DailyPainLog.log_date, start, end)
    pains = [
        {"date": row.log_date.isoformat(), "pain_level": row.pain_level}
        for row in q.order_by(DailyPainLog.log_date.asc()).all()
    ]

    today = today_local()
    pain_map = {date.fromisoformat(p["date"]): p["pain_level"] for p in pains}
    # build_segments 需要 setting 对象；用内存对象避免 get_settings 落库（工具只读）
    in_memory_setting = setting or CycleSetting(
        user_id=user_id, cycle_length=cycle_length, period_length=period_length
    )
    segments = cycle_service.build_segments(db, user_id, setting=in_memory_setting, today=today)
    segment = cycle_service.segment_for_day(segments, today)
    today_info = None
    if segment is not None:
        phase = cycle_service.phase_in_segment(today, segment)
        today_info = {
            "date": today.isoformat(),
            "cycle_day": (today - segment.start).days + 1,
            "segment_length": segment.length,
            "segment_start": segment.start.isoformat(),
            "segment_source": segment.source,
            "phase_key": phase,
            "phase_label": PHASE_LABELS.get(phase) if phase else None,
            "pain_level": pain_map.get(today, 0),
        }

    return {
        "range": _range_dict(start, end),
        "settings": {
            "cycle_length": cycle_length,
            "period_length": period_length,
            "is_default": setting is None,
        },
        "period_count": len(periods),
        "periods": periods,
        "pain_count": len(pains),
        "pain_logs": pains,
        "today": today_info,
        "note": "cycle_length / period_length 为参考值（未设置时按系统默认）；"
                 "periods 中 period_length、cycle_length 由记录实时派生，算不出为 null；"
                 "segment_source 区分真实记录段 / 漏记补推段 / 预测段。",
    }


# ---------- 个人信息 ----------

def profile_info(db: Session, user_id: int) -> dict:
    """个人基本信息（昵称 / 性别 / 年龄 / 注册时间）；不含密码等敏感字段。"""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise AppError(404, "用户不存在")
    return {
        "display_name": user.display_name,
        "gender": user.gender,
        "age": user.age,
        "status": user.status,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "note": "身高、体重等身体数据在身材数据中，不在基本资料里；本工具不返回密码等敏感字段。",
    }
