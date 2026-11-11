"""状态记录 service：三表 CRUD、跨表合并分页、当日聚合、月历阶段复用周期推算。

口径：
- 三类（食欲 / 肌肉疼痛 / 炎症）各一张表，同用户同类同一天一行（唯一约束在模型层）。
- 跨表列表：三表分别查询后在内存按日期倒序、id 倒序合并分页；个人日记量级可接受。
- 月历阶段复用 cycle.service.calendar_month 的七阶段推算，三档归并：
  经期（menstrual）/ 卵泡期·排卵（follicular_pre、ovulation_day、follicular_post）/ 黄体期（luteal_*）。
  男性账号或无月经记录时不展示阶段（phase 置空）。
"""
import calendar as _calendar
from datetime import date

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.cycle import service as cycle_service
from app.modules.state_record.models import (
    STATE_MODELS,
    STATE_TYPES,
    STATE_TYPE_LABELS,
)

# 七阶段 → 状态记录三档分组
PHASE_GROUP_MAP = {
    "menstrual": "menses",
    "follicular_pre": "foll",
    "ovulation_day": "foll",
    "follicular_post": "foll",
    "luteal_early": "luteal",
    "luteal_mid": "luteal",
    "luteal_late": "luteal",
}


def _model(type_key: str):
    model = STATE_MODELS.get(type_key)
    if model is None:
        raise AppError(400, "记录类型不合法")
    return model


def to_dict(row, type_key: str) -> dict:
    return {
        "id": row.id,
        "type": type_key,
        "type_label": STATE_TYPE_LABELS[type_key],
        "date": row.date.isoformat(),
        "star": row.star,
        "remark": row.remark,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_records(db: Session, user_id: int, page: int = 1, page_size: int = 10, type_filter: str | None = None) -> dict:
    """跨三表合并分页：日期倒序、id 倒序。"""
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    if type_filter and type_filter not in STATE_MODELS:
        raise AppError(400, "记录类型不合法")
    types = [type_filter] if type_filter else list(STATE_TYPES)
    rows = []
    for t in types:
        rows.extend(db.query(STATE_MODELS[t]).filter(STATE_MODELS[t].user_id == user_id).all())
    rows.sort(key=lambda r: (r.date, r.id), reverse=True)
    total = len(rows)
    start = (page - 1) * page_size
    page_rows = rows[start:start + page_size]
    return {
        "list": [to_dict(r, t) for r, t in ((row, _infer_type(row)) for row in page_rows)],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    }


def _infer_type(row) -> str:
    for t, model in STATE_MODELS.items():
        if isinstance(row, model):
            return t
    raise AppError(500, "未知记录类型")


def get_by_date(db: Session, user_id: int, day: date) -> dict:
    """当日三类记录：{type: dict|None}。"""
    result: dict[str, dict | None] = {t: None for t in STATE_TYPES}
    for t in STATE_TYPES:
        model = STATE_MODELS[t]
        row = db.query(model).filter(model.user_id == user_id, model.date == day).first()
        if row is not None:
            result[t] = to_dict(row, t)
    return result


def get_one(db: Session, user_id: int, type_key: str, record_id: int):
    model = _model(type_key)
    return db.query(model).filter(model.id == record_id, model.user_id == user_id).first()


def _assert_unique(db: Session, user_id: int, type_key: str, day: date, exclude_id: int | None = None) -> None:
    model = _model(type_key)
    q = db.query(model.id).filter(model.user_id == user_id, model.date == day)
    if exclude_id is not None:
        q = q.filter(model.id != exclude_id)
    if q.first():
        raise AppError(409, "该日期已有同类型记录")


def create_record(db: Session, user_id: int, data) -> dict:
    _assert_unique(db, user_id, data.type, data.date)
    model = _model(data.type)
    row = model(user_id=user_id, date=data.date, star=data.star, remark=data.remark)
    db.add(row)
    db.commit()
    db.refresh(row)
    return to_dict(row, data.type)


def update_record(db: Session, user_id: int, record_id: int, data) -> dict | None:
    row = get_one(db, user_id, data.type, record_id)
    if row is None:
        return None
    _assert_unique(db, user_id, data.type, data.date, exclude_id=record_id)
    row.date = data.date
    row.star = data.star
    row.remark = data.remark
    db.commit()
    db.refresh(row)
    return to_dict(row, data.type)


def delete_record(db: Session, user_id: int, type_key: str, record_id: int) -> bool:
    row = get_one(db, user_id, type_key, record_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def batch_delete(db: Session, user_id: int, items: list[dict]) -> dict:
    """跨表批量删除：按类型分组，返回成功删除的 [{id, type}]。"""
    deleted: list[dict] = []
    skipped: list[dict] = []
    grouped: dict[str, list[int]] = {}
    for item in items:
        grouped.setdefault(item["type"], []).append(item["id"])
    for type_key, ids in grouped.items():
        model = _model(type_key)
        unique_ids = list(dict.fromkeys(ids))
        rows = db.query(model).filter(model.user_id == user_id, model.id.in_(unique_ids)).all()
        found = {row.id for row in rows}
        for row in rows:
            db.delete(row)
        for rid in unique_ids:
            if rid in found:
                deleted.append({"id": rid, "type": type_key})
            else:
                skipped.append({"id": rid, "type": type_key})
    db.commit()
    return {"deleted": deleted, "skipped": skipped}


def calendar_with_records(db: Session, user, year: int, month: int) -> dict:
    """月历：复用周期推算阶段，附当日是否有状态记录；男性 / 无周期记录时阶段置空。"""
    cal = cycle_service.calendar_month(db, user.id, year, month)
    has_cycle = bool(cal["overview"]["has_records"]) and user.gender != "男"

    record_dates: set[str] = set()
    last_day = _calendar.monthrange(year, month)[1]
    month_start = date(year, month, 1)
    month_end = date(year, month, last_day)
    for t in STATE_TYPES:
        model = STATE_MODELS[t]
        rows = (
            db.query(model.date)
            .filter(model.user_id == user.id, model.date >= month_start, model.date <= month_end)
            .all()
        )
        record_dates.update(r[0].isoformat() for r in rows)

    days = []
    for d in cal["days"]:
        phase_key = d["phase_key"] if has_cycle else None
        days.append(
            {
                "date": d["date"],
                "phase_key": phase_key,
                "phase_group": PHASE_GROUP_MAP.get(phase_key) if phase_key else None,
                "phase_label": d["phase_label"] if phase_key else None,
                "has_record": d["date"] in record_dates,
            }
        )
    return {"year": year, "month": month, "days": days}
