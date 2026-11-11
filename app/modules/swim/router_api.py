"""游泳 API 路由（/api/swim-records，SW-01/02；2026-11 支持计划态 + 单日查询 + 批量导入）。"""
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.constants import SWIM_STROKES
from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.core.sport_ops import batch_delete
from app.core.sport_schemas import BatchDeleteIn
from app.modules.electronic_trainer.ai_import import run_import
from app.modules.swim.models import SwimRecord
from app.modules.auth.models import User
from app.modules.swim import ai_profile, excel_io, json_import, service
from app.modules.swim.schemas import SwimNoteIn, SwimRecordIn
from config import settings
from database import get_db

router = APIRouter(prefix="/api/swim-records", tags=["swim"])

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_IMPORT_BYTES = 20 * 1024 * 1024


@router.get("")
def list_swim(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = service.list_records(db, user.id, page, page_size)
    return {**result, "list": [service.to_dict(r) for r in result["list"]]}


@router.get("/daily")
def daily_swim(
    day: date = Query(..., alias="date"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """某日全部行（计划 + 记录），供单日详情页/总览弹窗。"""
    rows = service.get_by_date(db, user.id, day)
    return {"date": day.isoformat(), "list": [service.to_dict(r) for r in rows]}


# 注意：静态路径必须注册在 /{record_id} 之前，否则会被动态路由遮蔽。

@router.get("/template")
def download_swim_template(
    user: User = Depends(get_current_user),
):
    """下载游泳记录导入模板 xlsx：数据 Sheet（表头）+ 填写说明。"""
    buf = excel_io.build_template()
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type=XLSX_MEDIA,
        headers={"Content-Disposition": 'attachment; filename="swim_import_template.xlsx"'},
    )


@router.post("/import")
async def import_swim(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导入 Excel（.xlsx）：解析 → 行级校验 → 每条有效行新建一条记录（status=recorded）。
    失败行跳过并返回明细，不阻断其他行。
    """
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
        return {"ok": True, "imported": 0, "created_ids": [], "failed": errors}
    created_ids = service.bulk_create_records(db, user.id, valid)
    return {"ok": True, "imported": len(created_ids), "created_ids": created_ids, "failed": errors}


@router.post("/import-json")
def import_swim_json(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导入 JSON（{records: [...]}）：逐记录校验 → 每条有效记录新建一条记录（status=recorded）。"""
    raw_records = payload.get("records") if isinstance(payload, dict) else None
    if not raw_records or not isinstance(raw_records, list):
        raise AppError(400, "records 数组不能为空")
    if len(raw_records) > 500:
        raise AppError(400, "记录数量过多（上限 500 条）")
    valid, errors = json_import.validate_json_records(raw_records)
    if not valid:
        return {"ok": True, "imported": 0, "created_ids": [], "failed": errors}
    created_ids = service.bulk_create_records(db, user.id, valid)
    return {"ok": True, "imported": len(created_ids), "created_ids": created_ids, "failed": errors}


@router.post("/ai-import")
def ai_import_swim(
    prompt: str = Form(default="", max_length=settings.ai_import_max_prompt_chars),
    images: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """AI 导入：文字 + 可选图片 → 结构化识别 → 复用 JSON 导入的校验与落库（统一 recorded）。"""
    return run_import(profile=ai_profile.PROFILE, text=prompt, images=images, db=db, user=user)


@router.post("")
def create_swim(
    payload: SwimRecordIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _validate(payload)
    row = service.create_record(db, user.id, payload)
    return service.to_dict(row)


@router.post("/batch-delete")
def batch_delete_swim(
    payload: BatchDeleteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return batch_delete(db, SwimRecord, user.id, payload.ids)


@router.put("/{record_id}")
def update_swim(
    record_id: int,
    payload: SwimRecordIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _validate(payload)
    row = service.update_record(db, user.id, record_id, payload)
    if row is None:
        raise AppError(404, "记录不存在")
    return service.to_dict(row)


@router.delete("/{record_id}")
def delete_swim(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not service.delete_record(db, user.id, record_id):
        raise AppError(404, "记录不存在")
    return {"ok": True}


# ---------- 练后心得（1:1，2026-11） ----------

@router.get("/{record_id}/note")
def get_swim_note(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    note = service.get_note(db, user.id, record_id)
    return {"note": ({"id": note.id, "rating": note.rating, "stroke_insight": note.stroke_insight, "notes": note.notes} if note else None)}


@router.put("/{record_id}/note")
def put_swim_note(
    record_id: int,
    payload: SwimNoteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    note = service.upsert_note(
        db, user.id, record_id,
        rating=payload.rating,
        stroke_insight=payload.stroke_insight,
        notes=payload.notes,
    )
    return {"note": {"id": note.id, "rating": note.rating, "stroke_insight": note.stroke_insight, "notes": note.notes}}


@router.get("/stats")
def swim_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.stats(db, user.id)


def _validate(payload: SwimRecordIn):
    if payload.status == "recorded":
        if payload.distance_m is None:
            raise AppError(400, "记录态需填写距离")
        if payload.duration_s is None and not (payload.start_time and payload.end_time):
            raise AppError(400, "记录态需填写时长（或填写起止时间由系统推导）")
        if payload.start_time and payload.end_time and payload.end_time <= payload.start_time:
            raise AppError(400, "结束时间需晚于开始时间")
        if payload.main_stroke is not None and payload.main_stroke not in SWIM_STROKES:
            raise AppError(400, "主泳姿不合法")
    else:
        # 计划态：仅目标距离必填；时长、主泳姿、起止时间均为可选目标
        if payload.distance_m is None:
            raise AppError(400, "计划态需填写目标距离")
        if payload.start_time and payload.end_time and payload.end_time <= payload.start_time:
            raise AppError(400, "结束时间需晚于开始时间")
        if payload.main_stroke is not None and payload.main_stroke not in SWIM_STROKES:
            raise AppError(400, "主泳姿不合法")
