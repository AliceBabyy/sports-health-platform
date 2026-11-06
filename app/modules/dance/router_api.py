"""舞蹈 API 路由（/api/dance-records，DA-01；2026-11 支持计划态 + 单日查询 + Excel/JSON 导入）。"""
from datetime import date

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.core.sport_ops import batch_delete
from app.core.sport_schemas import BatchDeleteIn
from app.modules.dance.models import DanceRecord
from app.modules.auth.models import User
from app.modules.dance import excel_io, json_import, service
from app.modules.dance.schemas import DanceNoteIn, DanceRecordIn
from database import get_db

router = APIRouter(prefix="/api/dance-records", tags=["dance"])

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_IMPORT_BYTES = 20 * 1024 * 1024  # 导入文件上限 20MB


@router.get("")
def list_dance(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    dance_type: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = service.list_records(db, user.id, page, page_size, dance_type)
    return {**result, "list": [service.to_dict(r) for r in result["list"]]}


@router.get("/daily")
def daily_dance(
    day: date = Query(..., alias="date"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """某日全部行（计划 + 记录），供单日详情页/总览弹窗。"""
    rows = service.get_by_date(db, user.id, day)
    return {"date": day.isoformat(), "list": [service.to_dict(r) for r in rows]}


# ---------- Excel / JSON 导入（2026-11-04 新增，参考 training 模块） ----------
# 注意：静态路径必须注册在 /{record_id} 之前，否则会被动态路由遮蔽。

@router.get("/template")
def download_dance_template(
    user: User = Depends(get_current_user),
):
    """下载导入模板 xlsx：舞蹈记录数据 Sheet（表头）+ 填写说明。"""
    buf = excel_io.build_template()
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type=XLSX_MEDIA,
        headers={"Content-Disposition": 'attachment; filename="dance_record_import_template.xlsx"'},
    )


@router.post("/import")
async def import_dance(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导入 Excel（.xlsx）：解析 → 行级校验 → 每行新建一条舞蹈记录（status=recorded）。

    导入不会修改/覆盖已存在的记录；失败行不阻断其他行。
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
        return {"ok": True, "imported": 0, "created_ids": [], "failed": errors}

    created_ids: list[int] = []
    for row in valid:
        payload = DanceRecordIn(status="recorded", **row)
        rec = service.create_record(db, user.id, payload)
        created_ids.append(rec.id)
    return {"ok": True, "imported": len(created_ids), "created_ids": created_ids, "failed": errors}


@router.post("/import-json")
def import_dance_json(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导入 JSON（{records: [...]}）：逐行校验 → 每条有效记录新建一条舞蹈记录（status=recorded）。"""
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        raise AppError(400, "请求体需包含 records 数组")
    if not raw_records:
        raise AppError(400, "records 数组不能为空")
    if len(raw_records) > 500:
        raise AppError(400, "记录数量过多（上限 500 条）")
    valid, errors = json_import.validate_json_records(raw_records)
    if not valid:
        return {"ok": True, "imported": 0, "created_ids": [], "failed": errors}
    created_ids: list[int] = []
    for record_in in valid:
        rec = service.create_record(db, user.id, record_in)
        created_ids.append(rec.id)
    return {"ok": True, "imported": len(created_ids), "created_ids": created_ids, "failed": errors}


@router.post("")
def create_dance(
    payload: DanceRecordIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _validate(payload)
    row = service.create_record(db, user.id, payload)
    return service.to_dict(row)


@router.post("/batch-delete")
def batch_delete_dance(
    payload: BatchDeleteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return batch_delete(db, DanceRecord, user.id, payload.ids)


@router.put("/{record_id}")
def update_dance(
    record_id: int,
    payload: DanceRecordIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _validate(payload)
    row = service.update_record(db, user.id, record_id, payload)
    if row is None:
        raise AppError(404, "记录不存在")
    return service.to_dict(row)


@router.delete("/{record_id}")
def delete_dance(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not service.delete_record(db, user.id, record_id):
        raise AppError(404, "记录不存在")
    return {"ok": True}


# ---------- 练后心得（1:1，2026-11） ----------

@router.get("/{record_id}/note")
def get_dance_note(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    note = service.get_note(db, user.id, record_id)
    return {"note": ({"id": note.id, "rating": note.rating, "video_effect": note.video_effect, "notes": note.notes} if note else None)}


@router.put("/{record_id}/note")
def put_dance_note(
    record_id: int,
    payload: DanceNoteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    note = service.upsert_note(
        db, user.id, record_id,
        rating=payload.rating,
        video_effect=payload.video_effect,
        notes=payload.notes,
    )
    return {"note": {"id": note.id, "rating": note.rating, "video_effect": note.video_effect, "notes": note.notes}}


@router.get("/stats")
def dance_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.stats(db, user.id)


def _validate(payload: DanceRecordIn):
    if payload.status == "recorded":
        if not payload.dance_type or payload.stars is None:
            raise AppError(400, "记录态需填写舞种与星级")
    elif not payload.dance_type or payload.stars is None:
        raise AppError(400, "计划态需填写舞种与星级")
