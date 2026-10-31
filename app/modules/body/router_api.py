"""身材数据 API 路由（/api/body-metrics 系列，BD-01~04、BD-10~14）。"""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.constants import METRIC_KEYS, METRIC_LABELS, TREND_RANGES
from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.body import service as body_service
from app.modules.body import trend_service
from app.modules.body.schemas import MetricUpsertIn, MetricUpdateIn
from database import get_db

router = APIRouter(prefix="/api/body-metrics", tags=["body"])


def _row_dict(row) -> dict:
    return {
        "id": row.id,
        "metric_key": row.metric_key,
        "metric_label": METRIC_LABELS.get(row.metric_key, row.metric_key),
        "value": float(row.value),
        "record_date": row.record_date.isoformat(),
    }


@router.get("")
def list_metrics(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = body_service.list_records(db, user.id, page, page_size)
    # list 已按日期聚合：{record_date, values}，直接透传
    return result


@router.post("")
def upsert_metrics(
    payload: MetricUpsertIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.values:
        raise AppError(400, "至少填写一个指标")
    body_service.upsert_metrics(db, user.id, payload.record_date, payload.values)
    return {"ok": True, "record_date": payload.record_date.isoformat()}


@router.put("/{record_id}")
def update_metric(
    record_id: int,
    payload: MetricUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = body_service.update_record(db, user.id, record_id, payload.value, payload.record_date)
    if row is None:
        raise AppError(404, "记录不存在")
    return _row_dict(row)


@router.delete("/{record_id}")
def delete_metric(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not body_service.delete_record(db, user.id, record_id):
        raise AppError(404, "记录不存在")
    return {"ok": True}


@router.delete("")
def delete_day(
    record_date: date = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除某日全部指标记录（前端按日期行删除）。"""
    count = body_service.delete_day(db, user.id, record_date)
    return {"ok": True, "deleted": count}


@router.get("/latest")
def latest(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    snap = body_service.latest_snapshot(db, user.id)
    snap["metrics"] = METRIC_KEYS
    return snap


@router.get("/trend")
def trend(
    metric: str = Query("weight"),
    range: str = Query("month"),  # noqa: A002
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if metric not in METRIC_KEYS:
        raise AppError(400, "不支持的指标")
    if range not in TREND_RANGES:
        raise AppError(400, "不支持的档位")
    return trend_service.build_trend(db, user.id, metric, range)
