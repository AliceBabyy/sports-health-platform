"""身材数据 service（4 表拆分）：按组按日 upsert（同日覆盖 / 新日期继承最近非空值）、
最新快照合并 4 组 + BMI、按日期合并分页、趋势跨表取值、按日删除 4 组。"""
from datetime import date
from decimal import Decimal
from math import ceil

from sqlalchemy.orm import Session

from app.core.constants import BODY_COLUMNS, BODY_GROUPS, BODY_KEYS, BODY_LABELS, BODY_UNITS
from app.modules.body.models import (
    BodyBasicGoalRecord,
    BodyBasicRecord,
    BodyDimensionsGoalRecord,
    BodyDimensionsRecord,
)

# 分组 → 表模型
GROUP_MODELS = {
    "basic": BodyBasicRecord,
    "goal": BodyBasicGoalRecord,
    "girth": BodyDimensionsRecord,
    "target": BodyDimensionsGoalRecord,
}

VALID_GROUPS = ("basic", "goal", "girth", "target")

# 目标指标 key → 对应当前实际指标 key（目标体重→体重、目标体脂率→体脂率、目标围度→对应围度）
GOAL_CURRENT_KEYS = {
    "target_weight": "weight",
    "target_body_fat": "body_fat",
    "target_arm": "arm",
    "target_chest": "chest",
    "target_waist": "waist",
    "target_hip": "hip",
    "target_thigh": "thigh",
    "target_calf": "calf",
}


def _to_float(v) -> float | None:
    if v is None:
        return None
    return float(v)


def _model_of(metric_key: str):
    """指标 key → 所属表模型。"""
    from app.core.constants import BODY_FIELDS

    group = BODY_FIELDS[metric_key][3]
    return GROUP_MODELS[group]


def _inherit_value(db: Session, model, user_id: int, column: str, record_date: date) -> Decimal | None:
    """未填字段继承：该字段最近一次非空值（record_date 严格早于当前日期）。"""
    value = (
        db.query(getattr(model, column))
        .filter(
            model.user_id == user_id,
            getattr(model, column).isnot(None),
            model.record_date < record_date,
        )
        .order_by(model.record_date.desc())
        .first()
    )
    return value[0] if value else None


def upsert_group(db: Session, user_id: int, group: str, record_date: date, values: dict[str, float]) -> None:
    """按 (user_id, record_date, group) upsert：
    - 当日该组已有行 → 只覆盖提交字段（未提交字段保留原值，等价同日编辑）；
    - 当日无行（新记录）→ 未提交字段沿用该字段最近一次非空值（继承上一条最新）。"""
    if group not in GROUP_MODELS:
        raise ValueError(f"未知分组：{group}")
    model = GROUP_MODELS[group]
    row = (
        db.query(model)
        .filter(model.user_id == user_id, model.record_date == record_date)
        .first()
    )
    is_new = row is None
    if is_new:
        row = model(user_id=user_id, record_date=record_date)
        db.add(row)
    for key in BODY_GROUPS[group]:
        column = BODY_COLUMNS[key]
        value = values.get(key)
        if value is None:
            if is_new:
                inherited = _inherit_value(db, model, user_id, column, record_date)
                if inherited is not None:
                    setattr(row, column, inherited)
            continue
        setattr(row, column, Decimal(str(value)))
    db.commit()


def update_group_record(db: Session, user_id: int, group: str, record_date: date, values: dict[str, float]) -> bool:
    """单条更新：仅覆盖提交字段，未提交字段保留当日原值；当日该组无记录返回 False。"""
    if group not in GROUP_MODELS:
        raise ValueError(f"未知分组：{group}")
    model = GROUP_MODELS[group]
    row = (
        db.query(model)
        .filter(model.user_id == user_id, model.record_date == record_date)
        .first()
    )
    if row is None:
        return False
    for key in BODY_GROUPS[group]:
        value = values.get(key)
        if value is None:
            continue
        setattr(row, BODY_COLUMNS[key], Decimal(str(value)))
    db.commit()
    return True


def delete_day(db: Session, user_id: int, record_date: date) -> int:
    """删除某日 4 组全部记录，返回删除总条数。"""
    total = 0
    for model in GROUP_MODELS.values():
        deleted = (
            db.query(model)
            .filter(model.user_id == user_id, model.record_date == record_date)
            .delete(synchronize_session=False)
        )
        total += deleted
    db.commit()
    return total


def list_records(db: Session, user_id: int, page: int = 1, page_size: int = 10):
    """按日期合并 4 组记录：同一 record_date 的 4 组行合并为一行（values 含全部已填字段）。"""
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))

    merged: dict[date, dict[str, float]] = {}
    for group, keys in BODY_GROUPS.items():
        model = GROUP_MODELS[group]
        rows = (
            db.query(model.record_date, *[getattr(model, BODY_COLUMNS[k]) for k in keys])
            .filter(model.user_id == user_id)
            .all()
        )
        for row in rows:
            values = merged.setdefault(row[0], {})
            for i, key in enumerate(keys):
                value = row[i + 1]
                if value is not None:
                    values[key] = _to_float(value)

    dates = sorted(merged.keys(), reverse=True)
    total = len(dates)
    page_dates = dates[(page - 1) * page_size : page * page_size]
    return {
        "list": [{"record_date": d.isoformat(), "values": merged[d]} for d in page_dates],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": ceil(total / page_size) if total else 0,
    }


def all_group_rows(db: Session, user_id: int, groups: tuple[str, ...] = ("basic", "girth")):
    """Excel 导出用：按组返回全部记录 {group: [{record_date, values}]}，日期升序（可直接再导入）。"""
    result: dict[str, list[dict]] = {}
    for group in groups:
        keys = BODY_GROUPS[group]
        model = GROUP_MODELS[group]
        rows = (
            db.query(model.record_date, *[getattr(model, BODY_COLUMNS[k]) for k in keys])
            .filter(model.user_id == user_id)
            .order_by(model.record_date.asc())
            .all()
        )
        result[group] = [
            {
                "record_date": row[0],
                "values": {k: _to_float(row[i + 1]) for i, k in enumerate(keys) if row[i + 1] is not None},
            }
            for row in rows
        ]
    return result


def normalize_day_values(db: Session, user_id: int, metric_key: str) -> dict[date, float]:
    """趋势口径：某指标列 → {record_date: value}（按所属表取值，null 跳过）。"""
    column = BODY_COLUMNS.get(metric_key)
    if column is None:
        return {}
    model = _model_of(metric_key)
    rows = (
        db.query(model.record_date, getattr(model, column))
        .filter(model.user_id == user_id, getattr(model, column).isnot(None))
        .order_by(model.record_date.asc())
        .all()
    )
    return {d: _to_float(v) for d, v in rows}


def latest_snapshot(db: Session, user_id: int) -> dict:
    """各维度最新值 + 较上次差值/方向（组内最近两条）；BMI 实时计算。

    显示口径：每组取 record_date 最新一行；该行空字段按继承逻辑一般已有值，
    但仍可能为 None（从未填过），页面按「—」展示。
    """
    snap: dict = {}
    latest_dates: dict[str, str] = {}
    latest_rows: dict[str, object] = {}
    prev_rows: dict[str, object] = {}

    for group, keys in BODY_GROUPS.items():
        model = GROUP_MODELS[group]
        rows = (
            db.query(model)
            .filter(model.user_id == user_id)
            .order_by(model.record_date.desc())
            .limit(2)
            .all()
        )
        latest = rows[0] if rows else None
        prev = rows[1] if len(rows) > 1 else None
        latest_rows[group] = latest
        prev_rows[group] = prev
        if latest is not None:
            latest_dates[group] = latest.record_date.isoformat()
        for key in keys:
            column = BODY_COLUMNS[key]
            cur = _to_float(getattr(latest, column)) if latest else None
            old = _to_float(getattr(prev, column)) if prev else None
            snap[key] = {
                "value": cur,
                "record_date": latest.record_date.isoformat() if latest else None,
                "delta": round(cur - old, 2) if cur is not None and old is not None else None,
                "prev_value": old,
            }

    # BMI = 体重kg ÷ 身高m²（健康区间 18.5~23.9），身高取当日值/最近非空值
    basic_latest = latest_rows.get("basic")
    weight = snap["weight"]["value"]
    height = snap["height"]["value"]
    bmi = None
    if weight is not None and height is not None:
        bmi = round(weight / ((height / 100) ** 2), 1)
    elif weight is not None and basic_latest is not None:
        h_row = (
            db.query(BodyBasicRecord.height_cm)
            .filter(
                BodyBasicRecord.user_id == user_id,
                BodyBasicRecord.height_cm.isnot(None),
                BodyBasicRecord.record_date <= basic_latest.record_date,
            )
            .order_by(BodyBasicRecord.record_date.desc())
            .first()
        )
        if h_row and h_row[0] is not None:
            bmi = round(weight / ((float(h_row[0]) / 100) ** 2), 1)
    snap["bmi"] = bmi
    snap["bmi_state"] = _bmi_state(bmi)
    snap["latest_dates"] = latest_dates
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


def _goal_progress_meta(current: float | None, target: float, start: float | None, unit: str) -> tuple:
    """单个目标项的进度与鼓励性文案。

    进度口径：从该指标最早历史记录值（start）起算，
    进度 = (start − current) / (start − target)，目标视为下限（减重/减围）。
    返回 (pct, reached, remaining, msg)：
    - pct ∈ [0, 100]；口径不适用时 None；
    - reached = 当前 ≤ 目标（含四舍五入后相等）；
    - remaining = 当前 − 目标（>0 表示还差多少）。
    """
    if current is None:
        return None, None, None, "暂无当前记录"
    remaining = round(current - target, 1)
    if remaining <= 0:
        return 100, True, remaining, "已达成目标"
    if start is None:
        return None, False, remaining, f"还差 {remaining}{unit} 达目标"
    denom = round(start - target, 1)
    if denom > 0:
        pct = round((start - current) / denom * 100, 1)
        if pct >= 100:  # remaining>0 时不应发生，防御性收敛
            pct = 99.9
        if pct <= 0:
            return 0.0, False, remaining, f"还差 {remaining}{unit} · 从起始 {start}{unit} 出发，继续加油"
        return pct, False, remaining, f"已完成 {pct}%，还差 {remaining}{unit} 达目标"
    # 目标值不低于起始值：该进度口径不适用，仅展示差距
    return None, False, remaining, f"还差 {remaining}{unit} 达目标"


def goal_progress(db: Session, user_id: int) -> dict:
    """目标与进度：期望指标 + 目标围度的最新目标值，与对应当前实际值比较。

    返回 {"items": [...], "total": n, "missing": n}：
    - items 按目标 key 顺序，仅包含已设置目标值的项；
    - 每项 {key, label, unit, target, current, start, pct, reached, remaining, msg}：
      start = 该指标最早一条历史记录值（进度起算点）；
      pct = 进度（起始→目标方向上当前所处位置，0~100，口径不适用时 None）；
      reached = 当前 ≤ 目标；remaining = 当前 − 目标；msg = 鼓励性文案。
    """
    snap = latest_snapshot(db, user_id)
    items: list[dict] = []
    missing = 0
    for key, current_key in GOAL_CURRENT_KEYS.items():
        target = snap[key]["value"] if snap.get(key) else None
        if target is None:
            missing += 1
            continue
        label, unit = BODY_LABELS[key], BODY_UNITS[key]
        current = snap[current_key]["value"] if snap.get(current_key) else None
        series = normalize_day_values(db, user_id, current_key)
        start = series[list(series.keys())[0]] if series else None
        pct, reached, remaining, msg = _goal_progress_meta(current, target, start, unit)
        items.append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "target": target,
                "current": current,
                "start": start,
                "pct": pct,
                "reached": reached,
                "remaining": remaining,
                "msg": msg,
            }
        )
    return {"items": items, "total": len(items), "missing": missing}


# 达成成就 · 进度：卡片展示的 7 项指标（体重/体脂/臂围/腰围/臀围/大腿围/小腿围，不含胸围）
ACHIEVEMENT_KEYS = ["weight", "body_fat", "arm", "waist", "hip", "thigh", "calf"]


def achievement_progress(db: Session, user_id: int) -> dict:
    """达成成就：7 项指标「首次记录 → 最新记录」变化对比，展示已完成的成就（不与目标比较、不设进度）。

    返回 {"items": [...], "has_data": bool}：
    - items 固定 7 项（顺序同 ACHIEVEMENT_KEYS），每项
      {key, label, unit, current, start, start_date, delta, direction, change_msg, has_change}：
      start/start_date = 该指标最早一条历史记录值及其日期；current = 最新值；
      delta = start − current（保留 1 位小数，正=下降）；direction ∈ down/up/same；
      change_msg 为鼓励性文案（已减 Xunit / 较最初上升 Xunit / 与最初持平）；
      start 或 current 缺失 → delta/direction/change_msg/has_change 为 None/False；
    - has_data = 至少一项有当前或起始值（卡片据此决定空态）。
    """
    snap = latest_snapshot(db, user_id)
    items: list[dict] = []
    for key in ACHIEVEMENT_KEYS:
        label, unit = BODY_LABELS[key], BODY_UNITS[key]
        current = snap[key]["value"] if snap.get(key) else None
        series = normalize_day_values(db, user_id, key)
        start = series[list(series.keys())[0]] if series else None
        start_date = series and list(series.keys())[0]
        delta = direction = change_msg = None
        has_change = False
        if start is not None and current is not None:
            delta = round(start - current, 1)
            has_change = True
            if delta > 0:
                direction = "down"
                change_msg = f"已减 {delta} {unit}"
            elif delta < 0:
                direction = "up"
                change_msg = f"较最初上升 {-delta} {unit}"
            else:
                direction = "same"
                change_msg = "与最初持平"
        items.append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "current": current,
                "start": start,
                "start_date": start_date.strftime("%Y.%m.%d") if start_date else None,
                "delta": delta,
                "direction": direction,
                "change_msg": change_msg,
                "has_change": has_change,
            }
        )
    has_data = any(it["current"] is not None or it["start"] is not None for it in items)
    return {"items": items, "has_data": has_data}
