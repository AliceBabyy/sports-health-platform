"""健身训练 service：id 维度 CRUD、状态机（planned → recorded 一键完成训练）、历史。

2026-11 整改：一日可多个训练计划/记录，一律按 training_id 定位（不再按 (user_id, date) 唯一）。
2026-11-04 整改：started_at/saved_at 改名 start_time/end_time（DateTime），新增 duration_s（训练时长，秒）；
起止时间与训练时长仅记录态填写；填了起止时间且未手填时长时，按 end_time-start_time 自动推导。
- status 为 planned/recorded；历史记录仍可编辑与删除。
"""
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.constants import TR_STATUS_PLANNED, TR_STATUS_RECORDED, today_local
from app.core.exceptions import AppError
from app.core.sport_ops import batch_delete, require_recorded
from app.modules.training.models import TrainingNote, TrainingRecord, TrainingRecordItem


def _derive_duration_s(start_time, end_time, duration_s):
    """时长口径：手填 duration_s 优先；否则起止时间齐备时自动推导（秒，>0）。"""
    if duration_s is not None:
        return duration_s
    if start_time and end_time:
        secs = (end_time - start_time).total_seconds()
        return int(secs) if secs > 0 else None
    return None


def _item_dict(item: TrainingRecordItem) -> dict:
    return {
        "id": item.id,
        "sort": item.sort,
        "exercise_name": item.exercise_name,
        "body_part": item.body_part,
        "weight_kg": float(item.weight_kg) if item.weight_kg is not None else None,
        "sets": item.sets,
        "reps": item.reps,
        "target_weight_kg": float(item.target_weight_kg) if item.target_weight_kg is not None else None,
        "checked": item.checked,
    }


def _reps_number(reps: str | None) -> int | None:
    """reps 字符串化兼容：取首个数字段（如 '12'→12、'10+8'→10、空→None）。"""
    if reps is None:
        return None
    m = ""
    for ch in str(reps).strip():
        if ch.isdigit():
            m += ch
        elif m:
            break
    return int(m) if m else None


def _item_volume(item: TrainingRecordItem) -> float:
    """容量 = 重量 × 组数 × 每组个数（三者齐备才计入；reps 取首个数字段）。"""
    if item.weight_kg is None or item.sets is None:
        return 0.0
    reps = _reps_number(item.reps)
    if reps is None:
        return 0.0
    return float(item.weight_kg) * item.sets * reps


def plan_to_dict(plan: TrainingRecord | None) -> dict | None:
    if plan is None:
        return None
    items = plan.items if plan.items is not None else []
    total_volume = sum(_item_volume(i) for i in items)
    body_parts = list(dict.fromkeys(i.body_part for i in items if i.body_part))
    return {
        "id": plan.id,
        "date": plan.date.isoformat(),
        "status": plan.status,
        "remark": plan.remark,
        "start_time": plan.start_time.isoformat() if plan.start_time else None,
        "end_time": plan.end_time.isoformat() if plan.end_time else None,
        "duration_s": plan.duration_s,
        "avg_heart_rate": plan.avg_heart_rate,
        "max_heart_rate": plan.max_heart_rate,
        "calories": float(plan.calories) if plan.calories is not None else None,
        "item_count": len(items),
        "total_sets": sum((i.sets or 0) for i in items),
        "total_volume": round(total_volume, 1),
        "completed_count": sum(1 for i in items if i.checked),
        "body_parts_summary": " + ".join(body_parts) if body_parts else "",
        "items": [_item_dict(i) for i in items],
        "note": (
            {
                "id": plan.note.id,
                "rating": plan.note.rating,
                "best_movement": plan.note.best_movement,
                "notes": plan.note.notes,
                "next_steps": plan.note.next_steps,
                "status_text": plan.note.status_text,  # 旧版自由文本，仅历史数据
            }
            if plan.note
            else None
        ),
    }


# ---------- 练后心得（1:1，2026-11） ----------

def get_note(db: Session, user_id: int, training_id: int) -> TrainingNote | None:
    plan = get_plan(db, user_id, training_id)
    return plan.note if plan else None


def upsert_note(db: Session, user_id: int, training_id: int, *, rating, best_movement, notes, next_steps):
    """心得 upsert：计划归属校验 → 有则改、无则建。rating 限定 1~5。"""
    plan = get_plan_or_404(db, user_id, training_id)
    require_recorded(plan)
    if rating is not None and not (1 <= rating <= 5):
        raise AppError(400, "自我评估需为 1~5 星")
    note = plan.note
    if note is None:
        note = TrainingNote(training_id=plan.id)
        plan.note = note
    note.rating = rating
    note.best_movement = best_movement or None
    note.notes = notes or None
    note.next_steps = next_steps or None
    db.commit()
    db.refresh(note)
    return note


# ---------- 查询 ----------

def get_plan(db: Session, user_id: int, training_id: int) -> TrainingRecord | None:
    """按 training_id 取单个计划（校验归属）。"""
    return (
        db.query(TrainingRecord)
        .filter(TrainingRecord.id == training_id, TrainingRecord.user_id == user_id)
        .first()
    )


def get_plan_or_404(db: Session, user_id: int, training_id: int) -> TrainingRecord:
    plan = get_plan(db, user_id, training_id)
    if plan is None:
        raise AppError(404, "训练计划不存在")
    return plan


def get_plans_by_date(db: Session, user_id: int, date: date) -> list[TrainingRecord]:
    """某日全部计划/记录（按创建顺序，即 id 升序）。"""
    return (
        db.query(TrainingRecord)
        .filter(TrainingRecord.user_id == user_id, TrainingRecord.date == date)
        .order_by(TrainingRecord.id.asc())
        .all()
    )


# ---------- 写（id 维度 CRUD） ----------

def replace_items(plan: TrainingRecord, items_payload) -> None:
    """整体替换计划明细（保留勾选与期望重量字段按提交值；部位/重量/组数/个数可空）。"""
    plan.items.clear()
    for idx, payload in enumerate(items_payload):
        plan.items.append(
            TrainingRecordItem(
                sort=idx + 1,
                exercise_name=payload.exercise_name,
                body_part=payload.body_part or None,
                weight_kg=payload.weight_kg,
                sets=payload.sets,
                reps=payload.reps or None,
                target_weight_kg=payload.target_weight_kg,
                checked=payload.checked,
            )
        )


def create_plan(
    db: Session,
    user_id: int,
    date: date,
    items_payload,
    remark: str | None = None,
    status: str = TR_STATUS_PLANNED,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    duration_s: int | None = None,
    avg_heart_rate: int | None = None,
    max_heart_rate: int | None = None,
    calories=None,
) -> TrainingRecord:
    """新建计划/记录（TR-03）：一日可多个，无需查重；status 可指定（导入数据直接落 recorded，2026-11-04）。

    起止时间/时长计划态与记录态均可落库（均可空）；导入未显式给时刻时 end_time 取当前时刻。
    """
    plan = TrainingRecord(user_id=user_id, date=date, status=status, remark=remark or None)
    plan.start_time = start_time
    plan.end_time = end_time or (datetime.now() if status == TR_STATUS_RECORDED else None)
    plan.duration_s = _derive_duration_s(start_time, plan.end_time, duration_s)
    if status == TR_STATUS_RECORDED:
        plan.avg_heart_rate = avg_heart_rate
        plan.max_heart_rate = max_heart_rate
        plan.calories = calories
    db.add(plan)
    db.flush()
    replace_items(plan, items_payload)
    db.commit()
    db.refresh(plan)
    return plan


def update_plan(
    db: Session,
    user_id: int,
    training_id: int,
    date: date,
    items_payload,
    remark: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    duration_s: int | None = None,
    avg_heart_rate: int | None = None,
    max_heart_rate: int | None = None,
    calories=None,
) -> TrainingRecord:
    """编辑计划/记录（TR-03，含页面内「+ 追加一行」的落库路径）。

    2026-11-04 起放开 recorded 锁定：训练历史中的记录数据允许编辑（改动作明细/备注/归属日期）。
    编辑已记录时按 sort 保留原勾选状态（checked），避免完成度被清零。
    """
    plan = get_plan_or_404(db, user_id, training_id)
    plan.date = date
    plan.remark = remark or None
    plan.start_time = start_time
    plan.end_time = end_time
    plan.duration_s = _derive_duration_s(start_time, end_time, duration_s)
    if plan.status == TR_STATUS_RECORDED:
        old_checked = {i.sort: i.checked for i in plan.items}
        plan.avg_heart_rate = avg_heart_rate
        plan.max_heart_rate = max_heart_rate
        plan.calories = calories
        replace_items(plan, items_payload)
        for item in plan.items:
            if item.sort in old_checked:
                item.checked = old_checked[item.sort]
    else:
        replace_items(plan, items_payload)
    db.commit()
    db.refresh(plan)
    return plan


def delete_plan(db: Session, user_id: int, training_id: int) -> bool:
    """删除计划/记录（级联删 items/note）。2026-11-04 起放开 recorded 锁定，历史记录可删。"""
    plan = get_plan(db, user_id, training_id)
    if plan is None:
        return False
    db.delete(plan)
    db.commit()
    return True


def batch_delete_plans(db: Session, user_id: int, training_ids: list[int]) -> dict:
    return batch_delete(db, TrainingRecord, user_id, training_ids)


# ---------- 状态机（planned → recorded 一键完成训练） ----------

def complete_plan(db: Session, user_id: int, training_id: int) -> TrainingRecord:
    """一键完成训练（2026-11-03 替代原计时记录模式）：planned → recorded，写 end_time（不强制写起止/时长）。

    2026-11-04 起移除「仅当日」限制：任意日期的计划均可标记为完成训练；
    起止时间与训练时长可在记录编辑弹窗里补录。
    """
    plan = get_plan_or_404(db, user_id, training_id)
    if plan.status == TR_STATUS_RECORDED:
        raise AppError(400, "该计划已是训练记录，请勿重复完成")
    plan.status = TR_STATUS_RECORDED
    plan.end_time = datetime.now()
    db.commit()
    db.refresh(plan)
    return plan


def copy_plan_to_date(db: Session, user_id: int, training_id: int, target_date: date) -> TrainingRecord:
    """一键复用：以某计划/记录的动作明细与备注为模板，在目标日期新建一个 planned 计划（2026-11-04）。

    用于训练历史「一键设为当日计划」：复用以前练过的内容，today 新建计划（勾选状态不复用）。
    """
    src = get_plan_or_404(db, user_id, training_id)
    plan = TrainingRecord(user_id=user_id, date=target_date, status=TR_STATUS_PLANNED, remark=src.remark)
    db.add(plan)
    db.flush()
    for i in src.items:
        plan.items.append(
            TrainingRecordItem(
                sort=i.sort,
                exercise_name=i.exercise_name,
                body_part=i.body_part,
                weight_kg=i.weight_kg,
                sets=i.sets,
                reps=i.reps,
                target_weight_kg=i.target_weight_kg,
                checked=False,
            )
        )
    db.commit()
    db.refresh(plan)
    return plan


def history(db: Session, user_id: int, page: int = 1, page_size: int = 10):
    """Training plans and records, newest date and ID first."""
    from app.core.pagination import paginate

    q = db.query(TrainingRecord).filter(TrainingRecord.user_id == user_id)
    return paginate(q, page, page_size, order_by=(TrainingRecord.date.desc(), TrainingRecord.id.desc()))


def stats(db: Session, user_id: int) -> dict:
    """健身档案（2026-11-04，仿舞蹈档案）：本周/本月累计训练次数与训练时长，仅统计记录态。

    周口径：ISO 周（周一起始）；跨年边界用 isocalendar 的 (year, week) 统一判定。
    时长口径：手填 duration_s 优先，否则按起止时间推导（同 _derive_duration_s）。
    """
    rows = (
        db.query(TrainingRecord)
        .filter(TrainingRecord.user_id == user_id, TrainingRecord.status == TR_STATUS_RECORDED)
        .all()
    )
    now = datetime.now()
    iso = now.isocalendar()  # (year, week, weekday)
    week_count = 0
    week_duration_s = 0
    month_count = 0
    month_duration_s = 0
    for r in rows:
        dur = _derive_duration_s(r.start_time, r.end_time, r.duration_s) or 0
        d = r.date
        if d.isocalendar()[:2] == iso[:2]:
            week_count += 1
            week_duration_s += dur
        if d.year == now.year and d.month == now.month:
            month_count += 1
            month_duration_s += dur
    return {
        "week_count": week_count,
        "week_duration_s": week_duration_s,
        "month_count": month_count,
        "month_duration_s": month_duration_s,
    }
