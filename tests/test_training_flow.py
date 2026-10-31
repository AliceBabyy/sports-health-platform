"""健身训练单测（TR）：状态迁移、时长计算、记录后锁定、取消计时。"""
from datetime import date

import pytest

from app.core.constants import TR_STATUS_PLANNED, TR_STATUS_RECORDED, today_local
from app.core.exceptions import AppError
from app.modules.training import service
from app.modules.training.schemas import PlanItemIn

USER = 1

ITEM = PlanItemIn(exercise_name="杠铃深蹲", body_part="腿", weight_kg=70, sets=5, reps="8")
ITEM_MIX = PlanItemIn(exercise_name="杠铃卧推", body_part="胸", weight_kg=40, sets=3, reps="10+8+6")
ITEM_EMPTY = PlanItemIn(exercise_name="拉伸放松", body_part=None, weight_kg=None, sets=None, reps=None)


def _today():
    return today_local()


def test_save_and_get_plan(db):
    plan = service.save_plan(db, USER, _today(), [ITEM])
    assert plan.status == TR_STATUS_PLANNED
    data = service.plan_to_dict(plan)
    assert data["item_count"] == 1
    assert data["body_parts_summary"] == "腿"
    assert data["total_volume"] == 70 * 5 * 8
    assert data["items"][0]["sets"] == 5 and data["items"][0]["reps"] == "8"


def test_start_edit_vs_training(db):
    service.save_plan(db, USER, _today(), [ITEM])
    edit = service.start_record(db, USER, _today(), "edit")
    assert edit.started_at is None
    train = service.start_record(db, USER, _today(), "training")
    assert train.started_at is not None


def test_non_today_start_rejected(db):
    service.save_plan(db, USER, _today(), [ITEM])
    with pytest.raises(AppError):
        service.start_record(db, USER, date(2020, 1, 1), "training")


def test_save_record_locks_and_duration(db):
    from datetime import datetime, timedelta

    service.save_plan(db, USER, _today(), [ITEM])
    service.start_record(db, USER, _today(), "training")
    plan = service.get_plan(db, USER, _today())
    plan.started_at = datetime.now() - timedelta(minutes=33)
    db.commit()
    result = service.save_record(db, USER, _today(), [ITEM])
    assert result["item_count"] == 1
    assert result["duration_s"] is not None and 1980 <= result["duration_s"] <= 2040
    assert result["total_volume"] == 70 * 5 * 8
    assert service.get_plan(db, USER, _today()).status == TR_STATUS_RECORDED
    # 幂等保护：再次保存拒绝
    with pytest.raises(AppError):
        service.save_record(db, USER, _today(), [ITEM])
    # 已记录不可再修改计划
    with pytest.raises(AppError):
        service.save_plan(db, USER, _today(), [ITEM])


def test_save_record_edit_path_no_duration(db):
    service.save_plan(db, USER, _today(), [ITEM])
    service.start_record(db, USER, _today(), "edit")
    result = service.save_record(db, USER, _today(), [ITEM])
    assert result["duration_s"] is None


def test_cancel_clears_started_at(db):
    service.save_plan(db, USER, _today(), [ITEM])
    service.start_record(db, USER, _today(), "training")
    plan = service.cancel_record(db, USER, _today())
    assert plan.started_at is None
    assert plan.status == TR_STATUS_PLANNED


def test_note_save_and_read(db):
    service.save_plan(db, USER, _today(), [ITEM])
    service.save_record(db, USER, _today(), [ITEM])
    service.save_note(db, USER, _today(), "状态很好", 5)
    data = service.plan_to_dict(service.get_plan(db, USER, _today()))
    assert data["note"]["status_text"] == "状态很好"
    assert data["note"]["rating"] == 5


def test_history_only_recorded(db):
    service.save_plan(db, USER, _today(), [ITEM])
    h = service.history(db, USER)
    assert h["total"] == 0  # 未保存不进入历史
    service.save_record(db, USER, _today(), [ITEM])
    h = service.history(db, USER)
    assert h["total"] == 1


def test_reps_string_mixed_and_volume(db):
    """reps 字符串化：'10+8+6' 参与容量按首个数字段 10 计算；返回原样字符串。"""
    plan = service.save_plan(db, USER, _today(), [ITEM_MIX])
    data = service.plan_to_dict(plan)
    assert data["items"][0]["reps"] == "10+8+6"
    assert data["total_volume"] == 40 * 3 * 10


def test_nullable_fields_and_zero_volume(db):
    """部位/重量/组数/个数全部可空：透传 None，容量按 0 计。"""
    plan = service.save_plan(db, USER, _today(), [ITEM_EMPTY])
    data = service.plan_to_dict(plan)
    assert data["items"][0]["body_part"] is None
    assert data["items"][0]["weight_kg"] is None
    assert data["items"][0]["sets"] is None
    assert data["items"][0]["reps"] is None
    assert data["total_volume"] == 0
    assert data["total_sets"] == 0
