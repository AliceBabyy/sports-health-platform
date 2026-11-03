"""健身训练单测（TR，2026-11 整改：id 维度 CRUD / 一日多计划）：状态迁移、时长计算、记录后锁定、取消计时、多计划、批量删除。"""
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


def test_create_and_get_plan(db):
    plan = service.create_plan(db, USER, _today(), [ITEM])
    assert plan.status == TR_STATUS_PLANNED
    assert service.get_plan(db, USER, plan.id) is plan
    data = service.plan_to_dict(plan)
    assert data["item_count"] == 1
    assert data["body_parts_summary"] == "腿"
    assert data["total_volume"] == 70 * 5 * 8
    assert data["items"][0]["sets"] == 5 and data["items"][0]["reps"] == "8"


def test_multi_plans_same_day(db):
    """一日可多个计划，按 id 区分（不再有 (user_id, plan_date) 唯一约束）。"""
    p1 = service.create_plan(db, USER, _today(), [ITEM])
    p2 = service.create_plan(db, USER, _today(), [ITEM_MIX])
    p3 = service.create_plan(db, USER, _today(), [ITEM_EMPTY])
    assert len({p1.id, p2.id, p3.id}) == 3
    plans = service.get_plans_by_date(db, USER, _today())
    assert [p.id for p in plans] == [p1.id, p2.id, p3.id]
    # 归属校验：其他用户查不到
    assert service.get_plan(db, 999, p1.id) is None


def test_update_plan_edits_items(db):
    plan = service.create_plan(db, USER, _today(), [ITEM])
    plan2 = service.update_plan(db, USER, plan.id, [ITEM_MIX, ITEM_EMPTY])
    assert plan2.id == plan.id
    data = service.plan_to_dict(plan2)
    assert data["item_count"] == 2
    assert data["body_parts_summary"] == "胸"
    # 编辑后仍可查询
    data2 = service.plan_to_dict(service.get_plan(db, USER, plan.id))
    assert data2["items"][0]["reps"] == "10+8+6"


def test_update_recorded_rejected(db):
    plan = service.create_plan(db, USER, _today(), [ITEM])
    service.save_record(db, USER, plan.id, [ITEM])
    with pytest.raises(AppError):
        service.update_plan(db, USER, plan.id, [ITEM_MIX])


def test_start_edit_vs_training(db):
    plan = service.create_plan(db, USER, _today(), [ITEM])
    edit = service.start_record(db, USER, plan.id, "edit")
    assert edit.started_at is None
    train = service.start_record(db, USER, plan.id, "training")
    assert train.started_at is not None


def test_other_date_plan_start_rejected(db):
    """非当日计划不可切换为记录模式。"""
    plan = service.create_plan(db, USER, date(2020, 1, 1), [ITEM])
    with pytest.raises(AppError):
        service.start_record(db, USER, plan.id, "training")


def test_save_record_locks_and_duration(db):
    from datetime import datetime, timedelta

    plan = service.create_plan(db, USER, _today(), [ITEM])
    service.start_record(db, USER, plan.id, "training")
    plan.started_at = datetime.now() - timedelta(minutes=33)
    db.commit()
    result = service.save_record(db, USER, plan.id, [ITEM])
    assert result["item_count"] == 1
    assert result["duration_s"] is not None and 1980 <= result["duration_s"] <= 2040
    assert result["total_volume"] == 70 * 5 * 8
    assert service.get_plan(db, USER, plan.id).status == TR_STATUS_RECORDED
    # 幂等保护：再次保存拒绝
    with pytest.raises(AppError):
        service.save_record(db, USER, plan.id, [ITEM])
    # 已记录不可再修改计划 / 删除
    with pytest.raises(AppError):
        service.update_plan(db, USER, plan.id, [ITEM])
    with pytest.raises(AppError):
        service.delete_plan(db, USER, plan.id)


def test_save_record_edit_path_no_duration(db):
    plan = service.create_plan(db, USER, _today(), [ITEM])
    service.start_record(db, USER, plan.id, "edit")
    result = service.save_record(db, USER, plan.id, [ITEM])
    assert result["duration_s"] is None


def test_cancel_clears_started_at(db):
    plan = service.create_plan(db, USER, _today(), [ITEM])
    service.start_record(db, USER, plan.id, "training")
    plan2 = service.cancel_record(db, USER, plan.id)
    assert plan2.started_at is None
    assert plan2.status == TR_STATUS_PLANNED


def test_note_save_and_read(db):
    plan = service.create_plan(db, USER, _today(), [ITEM])
    service.save_record(db, USER, plan.id, [ITEM])
    service.save_note(db, USER, plan.id, "状态很好", 5)
    data = service.plan_to_dict(service.get_plan(db, USER, plan.id))
    assert data["note"]["status_text"] == "状态很好"
    assert data["note"]["rating"] == 5


def test_note_requires_recorded(db):
    plan = service.create_plan(db, USER, _today(), [ITEM])
    with pytest.raises(AppError):
        service.save_note(db, USER, plan.id, "还没练", 3)


def test_delete_and_batch_delete(db):
    p1 = service.create_plan(db, USER, _today(), [ITEM])
    p2 = service.create_plan(db, USER, _today(), [ITEM_MIX])
    p3 = service.create_plan(db, USER, _today(), [ITEM_EMPTY])
    # 单个删除
    assert service.delete_plan(db, USER, p1.id) is True
    assert service.get_plan(db, USER, p1.id) is None
    assert service.delete_plan(db, USER, p1.id) is False  # 不存在返回 False
    # 批量删除：p3 已保存记录 → 跳过
    service.save_record(db, USER, p3.id, [ITEM_EMPTY])
    res = service.batch_delete_plans(db, USER, [p2.id, p3.id, 999])
    assert set(res["deleted"]) == {p2.id}
    assert set(res["skipped"]) == {p3.id}
    assert service.get_plan(db, USER, p2.id) is None
    assert service.get_plan(db, USER, p3.id) is not None
    # 重复 id 去重
    res2 = service.batch_delete_plans(db, USER, [p3.id, p3.id])
    assert res2["deleted"] == [] and res2["skipped"] == [p3.id]


def test_history_only_recorded(db):
    p1 = service.create_plan(db, USER, _today(), [ITEM])
    h = service.history(db, USER)
    assert h["total"] == 0  # 未保存不进入历史
    service.save_record(db, USER, p1.id, [ITEM])
    h = service.history(db, USER)
    assert h["total"] == 1


def test_overview_week_includes_training(db):
    """周总览聚合（替代已删除的 week_plans）：训练计划计入 plans，保存记录计入 records。"""
    from app.core.constants import monday_of
    from app.modules.overview import service as overview

    monday = monday_of(_today())
    service.create_plan(db, USER, monday, [ITEM])
    p2 = service.create_plan(db, USER, monday, [ITEM_MIX])
    service.save_record(db, USER, p2.id, [ITEM_MIX])
    res = overview.aggregate(db, USER, "week", _today())
    assert len(res["days"]) == 7
    day0 = res["days"][0]
    assert day0["date"] == monday.isoformat()
    assert day0["sports"]["fitness"]["plans"] == 1
    assert day0["sports"]["fitness"]["records"] == 1
    assert res["stats"]["plans"] == 1 and res["stats"]["records"] == 1
    assert res["chart"]["labels"] == ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def test_reps_string_mixed_and_volume(db):
    """reps 字符串化：'10+8+6' 参与容量按首个数字段 10 计算；返回原样字符串。"""
    plan = service.create_plan(db, USER, _today(), [ITEM_MIX])
    data = service.plan_to_dict(plan)
    assert data["items"][0]["reps"] == "10+8+6"
    assert data["total_volume"] == 40 * 3 * 10


def test_nullable_fields_and_zero_volume(db):
    """部位/重量/组数/个数全部可空：透传 None，容量按 0 计。"""
    plan = service.create_plan(db, USER, _today(), [ITEM_EMPTY])
    data = service.plan_to_dict(plan)
    assert data["items"][0]["body_part"] is None
    assert data["items"][0]["weight_kg"] is None
    assert data["items"][0]["sets"] is None
    assert data["items"][0]["reps"] is None
    assert data["total_volume"] == 0
    assert data["total_sets"] == 0
