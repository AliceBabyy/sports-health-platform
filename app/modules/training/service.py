"""健身训练 service：id 维度 CRUD、状态机（planned → record(edit/training) → recorded）、时长计算、心得、历史。

2026-11 整改：一日可多个训练计划/记录，一律按 plan_id 定位（不再按 (user_id, plan_date) 唯一）。
状态机实现（规划 8.2）：
- status 字段记录终态 recorded；started_at 是否存在区分「仅编辑 / 开始训练」。
- 保存接口幂等保护：已是 recorded 拒绝再次保存；start/save/cancel 仅当日可执行。
- 时长 duration_s = saved_at - started_at（后端算，接口返回秒，前端展示分钟）。
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
            {"id": plan.note.id, "status_text": plan.note.status_text, "rating": plan.note.rating}
            if plan.note
            else None
        ),
    }


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


def create_plan(db: Session, user_id: int, plan_date: date, items_payload, remark: str | None = None) -> TrainingPlan:
    """新建计划（TR-03）：一日可多个，无需查重。"""
    plan = TrainingPlan(user_id=user_id, plan_date=plan_date, status=TR_STATUS_PLANNED, remark=remark or None)
    db.add(plan)
    db.flush()
    replace_items(plan, items_payload)
    db.commit()
    db.refresh(plan)
    return plan


def update_plan(db: Session, user_id: int, plan_id: int, items_payload, remark: str | None = None) -> TrainingPlan:
    """编辑计划（TR-03，含页面内「+ 追加一行」的落库路径）。已记录（recorded）锁定，不可再改。"""
    plan = get_plan_or_404(db, user_id, plan_id)
    if plan.status == TR_STATUS_RECORDED:
        raise AppError(400, "该计划已保存为训练记录，不可再修改")
    plan.remark = remark or None
    replace_items(plan, items_payload)
    db.commit()
    db.refresh(plan)
    return plan


def delete_plan(db: Session, user_id: int, plan_id: int) -> bool:
    """删除计划（级联删 items/note）。已记录（recorded）锁定，不可删除。"""
    plan = get_plan(db, user_id, plan_id)
    if plan is None:
        return False
    if plan.status == TR_STATUS_RECORDED:
        raise AppError(400, "该计划已保存为训练记录，不可删除")
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


# ---------- 状态机（按 plan_id） ----------

def start_record(db: Session, user_id: int, plan_id: int, mode: str) -> TrainingPlan:
    """进入记录模式（TR-10/11/16）：仅当日可切换；training 写 started_at。"""
    plan = get_plan_or_404(db, user_id, plan_id)
    if plan.plan_date != today_local():
        raise AppError(400, "仅当日计划可切换为记录模式")
    if plan.status == TR_STATUS_RECORDED:
        raise AppError(400, "该计划已保存为记录，不可再次进入记录模式")
    if mode == "training":
        plan.started_at = datetime.now()
        # 仅编辑路径不写 started_at
    db.commit()
    db.refresh(plan)
    return plan


def save_record(db: Session, user_id: int, plan_id: int, items_payload, remark: str | None = None) -> dict:
    """保存记录（TR-17/22）：落终值、写 saved_at、status=recorded、当日锁定。"""
    plan = get_plan_or_404(db, user_id, plan_id)
    if plan.plan_date != today_local():
        raise AppError(400, "仅当日可保存训练记录")
    if plan.status == TR_STATUS_RECORDED:
        raise AppError(400, "该计划已保存，请勿重复提交")
    now = datetime.now()
    if remark is not None:   # 保存记录时不传则保留计划备注
        plan.remark = remark or None
    replace_items(plan, items_payload)
    plan.status = TR_STATUS_RECORDED
    plan.saved_at = now
    db.commit()
    db.refresh(plan)

    duration_s = None
    if plan.started_at is not None:
        duration_s = max(0, int((now - plan.started_at).total_seconds()))
    return {
        "plan": plan_to_dict(plan),
        "duration_s": duration_s,
        "item_count": len(plan.items),
        "completed_count": sum(1 for i in plan.items if i.checked),
        "total_volume": round(sum(_item_volume(i) for i in plan.items), 1),
    }


def cancel_record(db: Session, user_id: int, plan_id: int) -> TrainingPlan | None:
    """取消记录模式：清空 started_at，回到计划态（未保存前可退出）。"""
    plan = get_plan(db, user_id, plan_id)
    if plan is None:
        return None
    if plan.plan_date != today_local():
        raise AppError(400, "仅当日可取消记录模式")
    if plan.status == TR_STATUS_RECORDED:
        raise AppError(400, "该计划已保存，不可取消")
    plan.started_at = None
    db.commit()
    db.refresh(plan)
    return plan


def save_note(db: Session, user_id: int, plan_id: int, status_text: str, rating: int | None) -> TrainingNote:
    """训练心得（TR-24/25）：关联该次训练，可 upsert；可跳过不影响主流程。"""
    plan = get_plan_or_404(db, user_id, plan_id)
    if plan.status != TR_STATUS_RECORDED:
        raise AppError(400, "仅已保存的训练记录可填写心得")
    note = db.query(TrainingNote).filter(TrainingNote.plan_id == plan.id).first()
    if note is None:
        note = TrainingNote(plan_id=plan.id, status_text=status_text or None, rating=rating)
        db.add(note)
    else:
        note.status_text = status_text or None
        note.rating = rating
    plan.note = note  # 维护双向关联：plan_to_dict 可能在写入前已把 note 缓存为 None，须回写
    db.commit()
    db.refresh(note)
    return note


def history(db: Session, user_id: int, page: int = 1, page_size: int = 10):
    """训练历史：已记录计划 + 心得，按日期倒序分页。"""
    from app.core.pagination import paginate

    q = (
        db.query(TrainingPlan)
        .filter(TrainingPlan.user_id == user_id, TrainingPlan.status == TR_STATUS_RECORDED)
    )
    return paginate(q, page, page_size, order_by=TrainingPlan.plan_date.desc())
