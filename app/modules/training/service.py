"""健身训练 service：id 维度 CRUD、状态机（planned → recorded 一键完成训练）、历史。

2026-11 整改：一日可多个训练计划/记录，一律按 plan_id 定位（不再按 (user_id, plan_date) 唯一）。
2026-11-03 整改：移除「开始训练/计时记录模式」（start/save/cancel 计时流程与心得填写入口），
改为计划卡「完成训练」一键转 recorded（写 saved_at，不写计时 started_at）；历史 recorded 数据保留。
- status 字段记录终态 recorded；update/delete 对 recorded 锁定。
- 时长：仅历史 recorded（带 started_at）可算；新完成训练无计时时长。
"""
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.core.constants import TR_STATUS_PLANNED, TR_STATUS_RECORDED, today_local
from app.core.exceptions import AppError
from app.modules.training.models import TrainingNote, TrainingPlan, TrainingPlanItem


def _item_dict(item: TrainingPlanItem) -> dict:
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


def _item_volume(item: TrainingPlanItem) -> float:
    """容量 = 重量 × 组数 × 每组个数（三者齐备才计入；reps 取首个数字段）。"""
    if item.weight_kg is None or item.sets is None:
        return 0.0
    reps = _reps_number(item.reps)
    if reps is None:
        return 0.0
    return float(item.weight_kg) * item.sets * reps


def plan_to_dict(plan: TrainingPlan | None) -> dict | None:
    if plan is None:
        return None
    items = plan.items if plan.items is not None else []
    total_volume = sum(_item_volume(i) for i in items)
    body_parts = list(dict.fromkeys(i.body_part for i in items if i.body_part))
    return {
        "id": plan.id,
        "plan_date": plan.plan_date.isoformat(),
        "status": plan.status,
        "remark": plan.remark,
        "started_at": plan.started_at.isoformat() if plan.started_at else None,
        "saved_at": plan.saved_at.isoformat() if plan.saved_at else None,
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
                "reflection": plan.note.reflection,
                "next_steps": plan.note.next_steps,
                "status_text": plan.note.status_text,  # 旧版自由文本，仅历史数据
            }
            if plan.note
            else None
        ),
    }


# ---------- 练后心得（1:1，2026-11） ----------

def get_note(db: Session, user_id: int, plan_id: int) -> TrainingNote | None:
    plan = get_plan(db, user_id, plan_id)
    return plan.note if plan else None


def upsert_note(db: Session, user_id: int, plan_id: int, *, rating, best_movement, reflection, next_steps):
    """心得 upsert：计划归属校验 → 有则改、无则建。rating 限定 1~5。"""
    plan = get_plan_or_404(db, user_id, plan_id)
    if rating is not None and not (1 <= rating <= 5):
        raise AppError(400, "自我评估需为 1~5 星")
    note = plan.note
    if note is None:
        note = TrainingNote(plan_id=plan.id)
        plan.note = note
    note.rating = rating
    note.best_movement = best_movement or None
    note.reflection = reflection or None
    note.next_steps = next_steps or None
    db.commit()
    db.refresh(note)
    return note


# ---------- 查询 ----------

def get_plan(db: Session, user_id: int, plan_id: int) -> TrainingPlan | None:
    """按 plan_id 取单个计划（校验归属）。"""
    return (
        db.query(TrainingPlan)
        .filter(TrainingPlan.id == plan_id, TrainingPlan.user_id == user_id)
        .first()
    )


def get_plan_or_404(db: Session, user_id: int, plan_id: int) -> TrainingPlan:
    plan = get_plan(db, user_id, plan_id)
    if plan is None:
        raise AppError(404, "训练计划不存在")
    return plan


def get_plans_by_date(db: Session, user_id: int, plan_date: date) -> list[TrainingPlan]:
    """某日全部计划/记录（按创建顺序，即 id 升序）。"""
    return (
        db.query(TrainingPlan)
        .filter(TrainingPlan.user_id == user_id, TrainingPlan.plan_date == plan_date)
        .order_by(TrainingPlan.id.asc())
        .all()
    )


# ---------- 写（id 维度 CRUD） ----------

def replace_items(plan: TrainingPlan, items_payload) -> None:
    """整体替换计划明细（保留勾选与期望重量字段按提交值；部位/重量/组数/个数可空）。"""
    plan.items.clear()
    for idx, payload in enumerate(items_payload):
        plan.items.append(
            TrainingPlanItem(
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
    plan_date: date,
    items_payload,
    remark: str | None = None,
    status: str = TR_STATUS_PLANNED,
) -> TrainingPlan:
    """新建计划/记录（TR-03）：一日可多个，无需查重；status 可指定（导入数据直接落 recorded，2026-11-04）。"""
    plan = TrainingPlan(user_id=user_id, plan_date=plan_date, status=status, remark=remark or None)
    if status == TR_STATUS_RECORDED:
        plan.saved_at = datetime.now()  # 导入即记录：保存时刻 = 导入时刻
    db.add(plan)
    db.flush()
    replace_items(plan, items_payload)
    db.commit()
    db.refresh(plan)
    return plan


def update_plan(db: Session, user_id: int, plan_id: int, plan_date: date, items_payload, remark: str | None = None) -> TrainingPlan:
    """编辑计划/记录（TR-03，含页面内「+ 追加一行」的落库路径）。

    2026-11-04 起放开 recorded 锁定：训练历史中的记录数据允许编辑（改动作明细/备注/归属日期）。
    编辑已记录时按 sort 保留原勾选状态（checked），避免完成度被清零。
    """
    plan = get_plan_or_404(db, user_id, plan_id)
    plan.plan_date = plan_date
    if plan.status == TR_STATUS_RECORDED:
        old_checked = {i.sort: i.checked for i in plan.items}
        plan.remark = remark or None
        replace_items(plan, items_payload)
        for item in plan.items:
            if item.sort in old_checked:
                item.checked = old_checked[item.sort]
    else:
        plan.remark = remark or None
        replace_items(plan, items_payload)
    db.commit()
    db.refresh(plan)
    return plan


def delete_plan(db: Session, user_id: int, plan_id: int) -> bool:
    """删除计划/记录（级联删 items/note）。2026-11-04 起放开 recorded 锁定，历史记录可删。"""
    plan = get_plan(db, user_id, plan_id)
    if plan is None:
        return False
    db.delete(plan)
    db.commit()
    return True


def batch_delete_plans(db: Session, user_id: int, plan_ids: list[int]) -> dict:
    """批量删除计划：仅删除未保存记录（planned）的计划；已记录的跳过并在 skipped 中返回。"""
    plan_ids = list(dict.fromkeys(plan_ids))
    plans = (
        db.query(TrainingPlan)
        .filter(TrainingPlan.user_id == user_id, TrainingPlan.id.in_(plan_ids))
        .all()
    )
    deleted: list[int] = []
    skipped: list[int] = []
    for p in plans:
        if p.status == TR_STATUS_RECORDED:
            skipped.append(p.id)
        else:
            db.delete(p)
            deleted.append(p.id)
    db.commit()
    return {"deleted": deleted, "skipped": skipped}


# ---------- 状态机（planned → recorded 一键完成训练） ----------

def complete_plan(db: Session, user_id: int, plan_id: int) -> TrainingPlan:
    """一键完成训练（2026-11-03 替代原计时记录模式）：planned → recorded，写 saved_at（不写计时 started_at）。

    2026-11-04 起移除「仅当日」限制：任意日期的计划均可标记为完成训练。
    """
    plan = get_plan_or_404(db, user_id, plan_id)
    if plan.status == TR_STATUS_RECORDED:
        raise AppError(400, "该计划已是训练记录，请勿重复完成")
    plan.status = TR_STATUS_RECORDED
    plan.saved_at = datetime.now()
    db.commit()
    db.refresh(plan)
    return plan


def copy_plan_to_date(db: Session, user_id: int, plan_id: int, target_date: date) -> TrainingPlan:
    """一键复用：以某计划/记录的动作明细与备注为模板，在目标日期新建一个 planned 计划（2026-11-04）。

    用于训练历史「一键设为当日计划」：复用以前练过的内容，today 新建计划（勾选状态不复用）。
    """
    src = get_plan_or_404(db, user_id, plan_id)
    plan = TrainingPlan(user_id=user_id, plan_date=target_date, status=TR_STATUS_PLANNED, remark=src.remark)
    db.add(plan)
    db.flush()
    for i in src.items:
        plan.items.append(
            TrainingPlanItem(
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
    """训练历史：已记录计划 + 心得，按日期倒序分页。"""
    from app.core.pagination import paginate

    q = (
        db.query(TrainingPlan)
        .filter(TrainingPlan.user_id == user_id, TrainingPlan.status == TR_STATUS_RECORDED)
    )
    return paginate(q, page, page_size, order_by=TrainingPlan.plan_date.desc())
