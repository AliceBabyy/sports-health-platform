"""健身训练 service：状态机（planned → record(edit/training) → recorded）、时长计算、心得、历史。

状态机实现（规划 8.2）：
- status 字段记录终态 recorded；started_at 是否存在区分「仅编辑 / 开始训练」。
- 保存接口幂等保护：已是 recorded 拒绝再次保存；非当日拒绝 start/save。
- 时长 duration_s = saved_at - started_at（后端算，接口返回秒，前端展示分钟）。
"""
from datetime import date, datetime, timedelta, timezone

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
        "weight_kg": float(item.weight_kg),
        "sets": item.sets,
        "reps": item.reps,
        "target_weight_kg": float(item.target_weight_kg) if item.target_weight_kg is not None else None,
        "checked": item.checked,
    }


def plan_to_dict(plan: TrainingPlan | None) -> dict | None:
    if plan is None:
        return None
    items = plan.items if plan.items is not None else []
    total_volume = sum(
        float(i.weight_kg) * i.sets * i.reps for i in items if i.weight_kg is not None
    )
    body_parts = list(dict.fromkeys(i.body_part for i in items if i.body_part))
    return {
        "id": plan.id,
        "plan_date": plan.plan_date.isoformat(),
        "status": plan.status,
        "started_at": plan.started_at.isoformat() if plan.started_at else None,
        "saved_at": plan.saved_at.isoformat() if plan.saved_at else None,
        "item_count": len(items),
        "total_sets": sum(i.sets for i in items),
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


def get_plan(db: Session, user_id: int, plan_date: date) -> TrainingPlan | None:
    return (
        db.query(TrainingPlan)
        .filter(TrainingPlan.user_id == user_id, TrainingPlan.plan_date == plan_date)
        .first()
    )


def replace_items(plan: TrainingPlan, items_payload) -> None:
    """整体替换计划明细（保留勾选与期望重量字段按提交值）。"""
    plan.items.clear()
    for idx, payload in enumerate(items_payload):
        plan.items.append(
            TrainingPlanItem(
                sort=idx + 1,
                exercise_name=payload.exercise_name,
                body_part=payload.body_part or "",
                weight_kg=payload.weight_kg,
                sets=payload.sets,
                reps=payload.reps,
                target_weight_kg=payload.target_weight_kg,
                checked=payload.checked,
            )
        )


def save_plan(db: Session, user_id: int, plan_date: date, items_payload) -> TrainingPlan:
    """新建/编辑计划（TR-03）。已记录（recorded）当日锁定，不可再改。"""
    plan = get_plan(db, user_id, plan_date)
    if plan is not None and plan.status == TR_STATUS_RECORDED:
        raise AppError(400, "该日训练已保存为记录，当日不可再修改计划")
    if plan is None:
        plan = TrainingPlan(user_id=user_id, plan_date=plan_date, status=TR_STATUS_PLANNED)
        db.add(plan)
        db.flush()
    replace_items(plan, items_payload)
    db.commit()
    db.refresh(plan)
    return plan


def delete_plan(db: Session, user_id: int, plan_date: date) -> bool:
    plan = get_plan(db, user_id, plan_date)
    if plan is None:
        return False
    if plan.status == TR_STATUS_RECORDED:
        raise AppError(400, "该日训练已保存为记录，不可删除")
    db.delete(plan)
    db.commit()
    return True


def week_plans(db: Session, user_id: int, week_start: date) -> list[dict]:
    """周面板（TR-02）：周一~周日七天计划（含空天）。"""
    days = [week_start + timedelta(days=i) for i in range(7)]
    plans = (
        db.query(TrainingPlan)
        .filter(TrainingPlan.user_id == user_id, TrainingPlan.plan_date.in_(days))
        .all()
    )
    by_date = {p.plan_date: p for p in plans}
    result = []
    for d in days:
        p = by_date.get(d)
        result.append(
            {
                "date": d.isoformat(),
                "plan": plan_to_dict(p) if p else None,
            }
        )
    return result


def start_record(db: Session, user_id: int, plan_date: date, mode: str) -> TrainingPlan:
    """进入记录模式（TR-10/11/16）：仅当日可切换；training 写 started_at。"""
    if plan_date != today_local():
        raise AppError(400, "仅当日计划可切换为记录模式")
    plan = get_plan(db, user_id, plan_date)
    if plan is None:
        raise AppError(404, "该日尚无训练计划，请先新建计划")
    if plan.status == TR_STATUS_RECORDED:
        raise AppError(400, "该日训练已保存为记录，不可再次进入记录模式")
    if mode == "training":
        plan.started_at = datetime.now()
        # 仅编辑路径不写 started_at
    db.commit()
    db.refresh(plan)
    return plan


def save_record(db: Session, user_id: int, plan_date: date, items_payload) -> dict:
    """保存记录（TR-17/22）：落终值、写 saved_at、status=recorded、当日锁定。"""
    if plan_date != today_local():
        raise AppError(400, "仅当日可保存训练记录")
    plan = get_plan(db, user_id, plan_date)
    if plan is None:
        raise AppError(404, "该日尚无训练计划")
    if plan.status == TR_STATUS_RECORDED:
        raise AppError(400, "该日训练已保存，请勿重复提交")
    now = datetime.now()
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
        "total_volume": round(
            sum(float(i.weight_kg) * i.sets * i.reps for i in plan.items if i.weight_kg is not None), 1
        ),
    }


def cancel_record(db: Session, user_id: int, plan_date: date) -> TrainingPlan | None:
    """取消记录模式：清空 started_at，回到计划态（未保存前可退出）。"""
    if plan_date != today_local():
        raise AppError(400, "仅当日可取消记录模式")
    plan = get_plan(db, user_id, plan_date)
    if plan is None:
        return None
    if plan.status == TR_STATUS_RECORDED:
        raise AppError(400, "该日训练已保存，不可取消")
    plan.started_at = None
    db.commit()
    db.refresh(plan)
    return plan


def save_note(db: Session, user_id: int, plan_date: date, status_text: str, rating: int | None) -> TrainingNote:
    """训练心得（TR-24/25）：关联该次训练，可 upsert；可跳过不影响主流程。"""
    plan = get_plan(db, user_id, plan_date)
    if plan is None:
        raise AppError(404, "该日无训练记录")
    note = db.query(TrainingNote).filter(TrainingNote.plan_id == plan.id).first()
    if note is None:
        note = TrainingNote(plan_id=plan.id, status_text=status_text or "", rating=rating)
        db.add(note)
    else:
        note.status_text = status_text or ""
        note.rating = rating
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
