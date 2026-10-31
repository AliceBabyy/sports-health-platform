"""身材数据 API 路由（/api/body-metrics 系列，4 表拆分：分组 upsert / 最新合并 / 趋势 / 按日删除 / Excel 导入导出）。"""
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.constants import BODY_GROUPS, BODY_LABELS, BODY_KEYS, TREND_KEYS, TREND_RANGES
from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.body import excel_io
from app.modules.body import service as body_service
from app.modules.body import trend_service
from app.modules.body.schemas import MetricUpsertIn
from database import get_db

router = APIRouter(prefix="/api/body-metrics", tags=["body"])

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_IMPORT_BYTES = 20 * 1024 * 1024  # 导入文件上限 20MB


@router.get("")
def list_metrics(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return body_service.list_records(db, user.id, page, page_size)


# ---------- Excel 导入导出（仅身材模块） ----------
# 注意：静态路径必须注册在 POST /{group} 之前，否则会被动态路由遮蔽（同段路径、同方法）。

@router.get("/template")
def download_template(
    user: User = Depends(get_current_user),
):
    """下载导入模板 xlsx：基础记录 / 维度记录（表头含单位）+ 填写说明。"""
    buf = excel_io.build_template()
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type=XLSX_MEDIA,
        headers={"Content-Disposition": 'attachment; filename="body_import_template.xlsx"'},
    )


@router.post("/import")
async def import_metrics(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导入 Excel（.xlsx）：解析 → 行级校验 → 按 (user_id, record_date, group) upsert。
    留空列沿用最近非空值，同日重复导入覆盖该日该组；失败行不阻断其他行。
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
    imported = 0
    for group in excel_io.IMPORT_GROUPS:
        # 升序写入，保证新日期留空字段能继承同一文件内更早行的值
        for row in sorted(valid[group], key=lambda r: r["record_date"]):
            body_service.upsert_group(db, user.id, group, row["record_date"], row["values"])
            imported += 1
    return {"ok": True, "imported": imported, "failed": errors}


@router.get("/export")
def export_metrics(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导出全部基础记录与维度记录为 xlsx（表头与导入模板一致，可直接再导入）。"""
    rows = body_service.all_group_rows(db, user.id)
    buf = excel_io.export_workbook(rows)
    stamp = date.today().isoformat()
    filename = f"身材数据_{stamp}.xlsx"
    disposition = (
        f"attachment; filename=\"body_metrics_{stamp}.xlsx\"; "
        f"filename*=UTF-8''{quote(filename)}"
    )
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type=XLSX_MEDIA,
        headers={"Content-Disposition": disposition},
    )


@router.post("/{group}")
def upsert_group(
    group: str,
    payload: MetricUpsertIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按组添加/覆盖：basic / goal / girth / target。
    当日该组已有行 → 覆盖提交字段；新日期 → 未填字段继承该字段最近非空值。"""
    if group not in BODY_GROUPS:
        raise AppError(400, "未知分组")
    if not payload.values:
        raise AppError(400, "至少填写一个指标")
    unknown = set(payload.values) - set(BODY_GROUPS[group])
    if unknown:
        raise AppError(400, f"该分组不支持字段：{'/'.join(sorted(unknown))}")
    body_service.upsert_group(db, user.id, group, payload.record_date, payload.values)
    return {"ok": True, "group": group, "record_date": payload.record_date.isoformat()}


@router.delete("")
def delete_day(
    record_date: date = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除某日 4 组全部记录（前端按日期行删除）。"""
    count = body_service.delete_day(db, user.id, record_date)
    return {"ok": True, "deleted": count}


@router.get("/latest")
def latest(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    snap = body_service.latest_snapshot(db, user.id)
    snap["metrics"] = BODY_KEYS
    snap["labels"] = BODY_LABELS
    return snap


@router.get("/trend")
def trend(
    metric: str = Query("weight"),
    range: str = Query("month"),  # noqa: A002
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if metric not in TREND_KEYS:
        raise AppError(400, "不支持的指标（目标值不参与趋势）")
    if range not in TREND_RANGES:
        raise AppError(400, "不支持的档位")
    return trend_service.build_trend(db, user.id, metric, range)
