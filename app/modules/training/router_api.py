"""健身计划与记录 API，统一挂在 /api/training 下。"""
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.core.constants import today_local
from app.core.sport_schemas import BatchDeleteIn
from app.modules.auth.models import User
from app.modules.training import excel_io, json_import, service
from app.modules.training.schemas import PlanCreateIn, PlanItemIn, PlanSaveIn, TrainingNoteIn
from database import get_db

router = APIRouter(prefix="/api/training", tags=["training"])

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_IMPORT_BYTES = 20 * 1024 * 1024  # 导入文件上限 20MB


@router.get("/daily")
def daily_training(
    day: date = Query(..., alias="date"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {
        "date": day.isoformat(),
        "list": [service.plan_to_dict(p) for p in service.get_plans_by_date(db, user.id, day)],
    }


@router.post("")
def create_plan(
    payload: PlanCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.items:
        raise AppError(400, "计划至少包含一条训练动作")
    plan = service.create_plan(
        db, user.id, payload.date, payload.items, payload.remark,
        status=payload.status,
        start_time=payload.start_time, end_time=payload.end_time, duration_s=payload.duration_s,
        avg_heart_rate=payload.avg_heart_rate, max_heart_rate=payload.max_heart_rate, calories=payload.calories,
    )
    return service.plan_to_dict(plan)


@router.post("/batch-delete")
def batch_delete(
    payload: BatchDeleteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.batch_delete_plans(db, user.id, payload.ids)


# ---------- Excel 导入（2026-11-04 新增，参考身材模块） ----------
# 注意：静态路径必须注册在 /{record_id} 之前，否则会被动态路由遮蔽（同段路径、同方法）。

@router.get("/template")
def download_plan_template(
    user: User = Depends(get_current_user),
):
    """下载导入模板 xlsx：训练计划数据 Sheet（表头）+ 填写说明。"""
    buf = excel_io.build_template()
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type=XLSX_MEDIA,
        headers={"Content-Disposition": 'attachment; filename="training_plan_import_template.xlsx"'},
    )


@router.post("/import")
async def import_plans(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """每行一个动作，按日期和训练组编号分组为记录；失败行不阻断其他行。"""
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise AppError(400, "仅支持 .xlsx 文件")
    content = await file.read()
    if not content:
        raise AppError(400, "文件为空")
    if len(content) > MAX_IMPORT_BYTES:
        raise AppError(400, "文件过大（上限 20MB）")
    try:
        parsed = excel_io.parse_workbook(content)
    except ValueError as exc:
        raise AppError(400, str(exc))
    valid, errors = excel_io.validate_rows(parsed)
    if not valid:
        return {"ok": True, "imported": 0, "created_ids": [], "items_imported": 0, "failed": errors}

    # 同日不同训练组分别建主表记录，动作保持文件行序。
    groups: dict[tuple[date, str], list[dict]] = {}
    for row in valid:
        groups.setdefault((row["date"], row["group_key"]), []).append(row)

    plans_created = 0
    items_imported = 0
    record_ids: list[int] = []
    for (date, _group_key), rows in groups.items():
        remark = next((r["remark"] for r in rows if r["remark"]), None)  # 取该组首个非空备注
        items = [
            PlanItemIn(
                exercise_name=r["exercise_name"],
                body_part=r["body_part"],
                weight_kg=r["weight_kg"],
                sets=r["sets"],
                reps=r["reps"],
                target_weight_kg=r["target_weight_kg"],
            )
            for r in rows
        ]
        plan = service.create_plan(db, user.id, date, items, remark=remark, status=service.TR_STATUS_RECORDED)
        plans_created += 1
        items_imported += len(items)
        record_ids.append(plan.id)
    return {"ok": True, "imported": plans_created, "created_ids": record_ids,
            "items_imported": items_imported, "failed": errors}


@router.post("/import-json")
def import_plans_json(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导入 JSON（{plans: [...]}）：逐计划校验 → 每个有效计划新建一条训练记录。

    语义与 Excel 导入一致：2026-11-04 起导入数据 status 直接为 recorded；不会修改已存在的计划/记录；
    失败计划跳过（含失败明细），不阻断其他计划。
    """
    raw_plans = payload.get("plans")
    if not isinstance(raw_plans, list):
        raise AppError(400, "请求体需包含 plans 数组")
    if not raw_plans:
        raise AppError(400, "plans 数组不能为空")
    if len(raw_plans) > 200:
        raise AppError(400, "计划数量过多（上限 200 个）")
    valid, errors = json_import.validate_json_plans(raw_plans)
    if not valid:
        return {"ok": True, "imported": 0, "created_ids": [], "items_imported": 0, "failed": errors}
    plans_created = 0
    items_imported = 0
    record_ids: list[int] = []
    for plan_in in valid:
        plan = service.create_plan(db, user.id, plan_in.date, plan_in.items, remark=plan_in.remark, status=service.TR_STATUS_RECORDED)
        plans_created += 1
        items_imported += len(plan_in.items)
        record_ids.append(plan.id)
    return {"ok": True, "imported": plans_created, "created_ids": record_ids,
            "items_imported": items_imported, "failed": errors}


@router.post("/{record_id}/copy-to-today")
def copy_plan_to_today(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """一键复用：以历史计划/记录为模板，在今日新建一个 planned 计划（2026-11-04）。

    用于训练历史「一键设为当日计划」：复用以前的训练内容。
    """
    plan = service.copy_plan_to_date(db, user.id, record_id, today_local())
    return {"plan": service.plan_to_dict(plan)}


@router.put("/{record_id}")
def update_plan(
    record_id: int,
    payload: PlanSaveIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.items:
        raise AppError(400, "计划至少包含一条训练动作")
    plan = service.update_plan(
        db, user.id, record_id, payload.date, payload.items, payload.remark,
        start_time=payload.start_time, end_time=payload.end_time, duration_s=payload.duration_s,
        avg_heart_rate=payload.avg_heart_rate, max_heart_rate=payload.max_heart_rate, calories=payload.calories,
    )
    return service.plan_to_dict(plan)


@router.delete("/{record_id}")
def delete_plan(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not service.delete_plan(db, user.id, record_id):
        raise AppError(404, "训练计划不存在")
    return {"ok": True}


@router.post("/{record_id}/complete")
def complete_plan(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = service.complete_plan(db, user.id, record_id)
    return {"plan": service.plan_to_dict(plan)}


# ---------- 练后心得（1:1，2026-11） ----------

@router.get("/{record_id}/note")
def get_plan_note(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    note = service.get_note(db, user.id, record_id)
    return {"note": (
        {"id": note.id, "rating": note.rating, "best_movement": note.best_movement,
         "notes": note.notes, "next_steps": note.next_steps}
        if note else None
    )}


@router.put("/{record_id}/note")
def put_plan_note(
    record_id: int,
    payload: TrainingNoteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    note = service.upsert_note(
        db, user.id, record_id,
        rating=payload.rating,
        best_movement=payload.best_movement,
        notes=payload.notes,
        next_steps=payload.next_steps,
    )
    return {"note": {"id": note.id, "rating": note.rating, "best_movement": note.best_movement,
                     "notes": note.notes, "next_steps": note.next_steps}}


@router.get("")
def list_training(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = service.history(db, user.id, page, page_size)
    return {**result, "list": [service.plan_to_dict(p) for p in result["list"]]}


@router.get("/stats")
def training_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.stats(db, user.id)
