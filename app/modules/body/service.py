"""身材数据 service（4 表拆分）：按组按日 upsert（同日覆盖 / 新日期继承最近非空值）、
最新快照合并 4 组 + BMI、按日期合并分页、趋势跨表取值、按日删除 4 组。"""
from datetime import date
from decimal import Decimal
from math import ceil

from sqlalchemy.orm import Session

from app.core.constants import BODY_COLUMNS, BODY_GROUPS, BODY_KEYS
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
