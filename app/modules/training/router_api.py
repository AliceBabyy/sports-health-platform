"""健身训练 API 路由（TR-01~03、TR-24；2026-11 整改：id 维度 CRUD；2026-11-03 移除记录模式状态机）。

一日可多个训练计划/记录，接口一律按 plan_id 定位：
- GET  /plans?plan_date=      某日全部计划列表
- POST /plans                  新建计划（body: plan_date + items + remark）
- GET  /plans/template         下载 Excel 导入模板（2026-11-04 新增）
- POST /plans/import           批量导入训练计划（.xlsx，按日期分组建计划）
- GET/PUT/DELETE /plans/{plan_id}  单个计划查询/编辑/删除（已记录锁定）
- POST /plans/batch-delete     批量删除（仅 planned，已记录的跳过）
- POST /plans/{plan_id}/complete  一键完成训练（planned → recorded，2026-11-04 起不限当日）
- POST /plans/{plan_id}/copy-to-today  一键复用：以历史计划/记录为模板在今日新建计划（2026-11-04）
注意：/plans/template、/plans/import、/plans/batch-delete 等静态路径必须注册在
/plans/{plan_id} 之前，否则会被动态路由遮蔽（同段路径、同方法）。
周/月跨运动总览已迁移至 /api/overview（2026-11），本模块不再提供 /plans/week。
"""
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.core.constants import today_local
from app.modules.auth.models import User
from app.modules.training import excel_io, json_import, service
from app.modules.training.schemas import BatchDeleteIn, PlanCreateIn, PlanItemIn, PlanSaveIn, TrainingNoteIn
from database import get_db

router = APIRouter(prefix="/api/training", tags=["training"])

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_IMPORT_BYTES = 20 * 1024 * 1024  # 导入文件上限 20MB


@router.get("/plans")
def list_plans(
    plan_date: date = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {
        "plan_date": plan_date.isoformat(),
        "plans": [service.plan_to_dict(p) for p in service.get_plans_by_date(db, user.id, plan_date)],
    }


@router.post("/plans")
def create_plan(
    payload: PlanCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.items:
        raise AppError(400, "计划至少包含一条训练动作")
    plan = service.create_plan(db, user.id, payload.plan_date, payload.items, payload.remark, status=payload.status)
    return {"plan": service.plan_to_dict(plan)}


@router.post("/plans/batch-delete")
def batch_delete(
    payload: BatchDeleteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.batch_delete_plans(db, user.id, payload.ids)


# ---------- Excel 导入（2026-11-04 新增，参考身材模块） ----------
# 注意：静态路径必须注册在 /plans/{plan_id} 之前，否则会被动态路由遮蔽（同段路径、同方法）。

@router.get("/plans/template")
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


@router.post("/plans/import")
async def import_plans(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导入 Excel（.xlsx）：解析 → 行级校验 → 按计划日期分组，每组新建一条训练记录。

    每行一个动作；同日期多行合并为一条记录（动作按行序）；2026-11-04 起导入数据 status 直接为 recorded
    （训练记录），导入不会修改已存在的计划/记录。失败行不阻断其他行。
    """
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
        return {"ok": True, "plans_created": 0, "items_imported": 0, "failed": errors}

    # 按计划日期分组，保持文件行序（dict 保持插入顺序）
    groups: dict[date, list[dict]] = {}
    for row in valid:
        groups.setdefault(row["plan_date"], []).append(row)

    plans_created = 0
    items_imported = 0
    plan_ids: list[int] = []
    for plan_date, rows in groups.items():
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
        plan = service.create_plan(db, user.id, plan_date, items, remark=remark, status=service.TR_STATUS_RECORDED)
        plans_created += 1
        items_imported += len(items)
        plan_ids.append(plan.id)
    return {"ok": True, "plans_created": plans_created, "items_imported": items_imported, "plan_ids": plan_ids, "failed": errors}


@router.post("/plans/import-json")
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
        return {"ok": True, "plans_created": 0, "items_imported": 0, "failed": errors}
    plans_created = 0
    items_imported = 0
    plan_ids: list[int] = []
    for plan_in in valid:
        plan = service.create_plan(db, user.id, plan_in.plan_date, plan_in.items, remark=plan_in.remark, status=service.TR_STATUS_RECORDED)
        plans_created += 1
        items_imported += len(plan_in.items)
        plan_ids.append(plan.id)
    return {"ok": True, "plans_created": plans_created, "items_imported": items_imported, "plan_ids": plan_ids, "failed": errors}


@router.post("/plans/{plan_id}/copy-to-today")
def copy_plan_to_today(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """一键复用：以历史计划/记录为模板，在今日新建一个 planned 计划（2026-11-04）。

    用于训练历史「一键设为当日计划」：复用以前的训练内容。
    """
    plan = service.copy_plan_to_date(db, user.id, plan_id, today_local())
    return {"plan": service.plan_to_dict(plan)}


@router.get("/plans/{plan_id}")
def get_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"plan": service.plan_to_dict(service.get_plan_or_404(db, user.id, plan_id))}


@router.put("/plans/{plan_id}")
def update_plan(
    plan_id: int,
    payload: PlanSaveIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.items:
        raise AppError(400, "计划至少包含一条训练动作")
    plan = service.update_plan(db, user.id, plan_id, payload.plan_date, payload.items, payload.remark)
    return {"plan": service.plan_to_dict(plan)}


@router.delete("/plans/{plan_id}")
def delete_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not service.delete_plan(db, user.id, plan_id):
        raise AppError(404, "训练计划不存在")
    return {"ok": True}


@router.post("/plans/{plan_id}/complete")
def complete_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = service.complete_plan(db, user.id, plan_id)
    return {"plan": service.plan_to_dict(plan)}


# ---------- 练后心得（1:1，2026-11） ----------

@router.get("/plans/{plan_id}/note")
def get_plan_note(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    note = service.get_note(db, user.id, plan_id)
    return {"note": (
        {"id": note.id, "rating": note.rating, "best_movement": note.best_movement,
         "reflection": note.reflection, "next_steps": note.next_steps}
        if note else None
    )}


@router.put("/plans/{plan_id}/note")
def put_plan_note(
    plan_id: int,
    payload: TrainingNoteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    note = service.upsert_note(
        db, user.id, plan_id,
        rating=payload.rating,
        best_movement=payload.best_movement,
        reflection=payload.reflection,
        next_steps=payload.next_steps,
    )
    return {"note": {"id": note.id, "rating": note.rating, "best_movement": note.best_movement,
                     "reflection": note.reflection, "next_steps": note.next_steps}}


@router.get("/history")
def history(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = service.history(db, user.id, page, page_size)
    return {**result, "list": [service.plan_to_dict(p) for p in result["list"]]}
