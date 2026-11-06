"""Operations shared by sport record modules."""
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.sport_contract import SportStatus


def validate_status_change(current: SportStatus, requested: SportStatus) -> None:
    if current == SportStatus.RECORDED and requested == SportStatus.PLANNED:
        raise AppError(400, "已完成的记录不能改回计划")


def require_recorded(row) -> None:
    if row.status != SportStatus.RECORDED:
        raise AppError(400, "只有已完成的记录可以填写心得")


def batch_delete(db: Session, model, user_id: int, ids: list[int]) -> dict:
    unique_ids = list(dict.fromkeys(ids))
    rows = db.query(model).filter(model.user_id == user_id, model.id.in_(unique_ids)).all()
    found = {row.id: row for row in rows}
    for row in rows:
        db.delete(row)
    db.commit()
    return {"deleted": [id for id in unique_ids if id in found],
            "skipped": [id for id in unique_ids if id not in found]}
