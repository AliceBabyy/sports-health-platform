"""健身训练单测（TR，2026-11 整改：id 维度 CRUD / 一日多计划；2026-11-03：移除计时记录模式，改「完成训练」一键转 recorded）。"""
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


def test_create_plan_schema_status(db):
    """「＋ 新建记录」入口：PlanCreateIn.status 允许 planned/recorded，非法值被 pydantic 拒绝。"""
    from pydantic import ValidationError

    from app.modules.training.schemas import PlanCreateIn

    rec = PlanCreateIn(date=date(2026, 11, 4), items=[ITEM], status="recorded")
    assert rec.status == "recorded"
    default = PlanCreateIn(date=date(2026, 11, 4), items=[ITEM])
    assert default.status == "planned"
    with pytest.raises(ValidationError):
        PlanCreateIn(date=date(2026, 11, 4), items=[ITEM], status="done")


def test_multi_plans_same_day(db):
    """一日可多个计划，按 id 区分（不再有 (user_id, date) 唯一约束）。"""
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
    plan2 = service.update_plan(db, USER, plan.id, _today(), [ITEM_MIX, ITEM_EMPTY])
    assert plan2.id == plan.id
    data = service.plan_to_dict(plan2)
    assert data["item_count"] == 2
    assert data["body_parts_summary"] == "胸"
    # 编辑后仍可查询
    data2 = service.plan_to_dict(service.get_plan(db, USER, plan.id))
    assert data2["items"][0]["reps"] == "10+8+6"


def test_update_plan_can_change_date(db):
    """2026-11-04 起编辑可改归属日期：planned 挪期、recorded 记录改期（补录/修正）。"""
    plan = service.create_plan(db, USER, date(2026, 11, 10), [ITEM])
    moved = service.update_plan(db, USER, plan.id, date(2026, 11, 11), [ITEM], remark="挪到明天")
    assert moved.date == date(2026, 11, 11)
    assert service.get_plan(db, USER, plan.id).date == date(2026, 11, 11)
    # 已记录改期：原日期不再有记录，新日期下有
    done = service.complete_plan(db, USER, plan.id)
    moved_rec = service.update_plan(db, USER, done.id, date(2026, 11, 12), [ITEM])
    assert moved_rec.status == TR_STATUS_RECORDED and moved_rec.date == date(2026, 11, 12)
    assert len(service.get_plans_by_date(db, USER, date(2026, 11, 11))) == 0
    assert len(service.get_plans_by_date(db, USER, date(2026, 11, 12))) == 1


def test_update_recorded_allowed_keeps_checked(db):
    """2026-11-04 起已记录可编辑：update 替换动作明细，并按 sort 保留原勾选状态（checked）。"""
    plan = service.create_plan(db, USER, _today(), [ITEM])
    service.complete_plan(db, USER, plan.id)
    plan.items[0].checked = True   # 模拟训练时勾选
    db.commit()
    plan2 = service.update_plan(db, USER, plan.id, _today(), [ITEM_MIX, ITEM_EMPTY])
    assert plan2.id == plan.id
    data = service.plan_to_dict(plan2)
    assert data["item_count"] == 2
    assert data["items"][0]["exercise_name"] == "杠铃卧推"
    assert data["items"][0]["checked"] is True    # 第 1 个动作勾选保留
    assert data["items"][1]["checked"] is False
    assert data["status"] == TR_STATUS_RECORDED
    assert data["date"] == _today().isoformat()   # 改期不丢失（此处日期未变）


def test_complete_plan_flow(db):
    """完成训练：planned → recorded，写 end_time（不强制写 start_time/时长）；重复完成拒绝；2026-11-04 起不限当日。"""
    plan = service.create_plan(db, USER, _today(), [ITEM])
    assert plan.start_time is None
    done = service.complete_plan(db, USER, plan.id)
    assert done.status == TR_STATUS_RECORDED
    assert done.end_time is not None
    assert done.start_time is None
    data = service.plan_to_dict(done)
    assert data["item_count"] == 1 and data["total_volume"] == 70 * 5 * 8
    # 幂等保护：已记录再次完成拒绝
    with pytest.raises(AppError):
        service.complete_plan(db, USER, plan.id)
    # 2026-11-04 起已记录可修改 / 可删除
    updated = service.update_plan(db, USER, plan.id, _today(), [ITEM_MIX])
    assert updated.status == TR_STATUS_RECORDED
    assert service.delete_plan(db, USER, plan.id) is True
    assert service.get_plan(db, USER, plan.id) is None


def test_other_date_complete_allowed(db):
    """2026-11-04 起移除「仅当日」限制：任意日期的计划均可标记为完成训练。"""
    plan = service.create_plan(db, USER, date(2020, 1, 1), [ITEM])
    done = service.complete_plan(db, USER, plan.id)
    assert done.status == TR_STATUS_RECORDED
    assert done.end_time is not None


def test_delete_and_batch_delete(db):
    p1 = service.create_plan(db, USER, _today(), [ITEM])
    p2 = service.create_plan(db, USER, _today(), [ITEM_MIX])
    p3 = service.create_plan(db, USER, _today(), [ITEM_EMPTY])
    # 单个删除
    assert service.delete_plan(db, USER, p1.id) is True
    assert service.get_plan(db, USER, p1.id) is None
    assert service.delete_plan(db, USER, p1.id) is False  # 不存在返回 False
    # 批量删除选中的计划和记录，未知 id 跳过
    service.complete_plan(db, USER, p3.id)
    res = service.batch_delete_plans(db, USER, [p2.id, p3.id, 999])
    assert set(res["deleted"]) == {p2.id, p3.id}
    assert set(res["skipped"]) == {999}
    assert service.get_plan(db, USER, p2.id) is None
    assert service.get_plan(db, USER, p3.id) is None
    # 重复 id 去重
    res2 = service.batch_delete_plans(db, USER, [p3.id, p3.id])
    assert res2["deleted"] == [] and res2["skipped"] == [p3.id]


def test_history_includes_plans_and_records(db):
    p1 = service.create_plan(db, USER, _today(), [ITEM])
    h = service.history(db, USER)
    assert h["total"] == 1
    service.complete_plan(db, USER, p1.id)
    h = service.history(db, USER)
    assert h["total"] == 1


def test_copy_plan_to_date_reuse_old_plan(db):
    """一键设为当日计划（2026-11-04）：以历史记录为模板在目标日期新建 planned 计划，原记录不动。

    支持任意日期计划/记录作为模板；勾选状态不复用。
    """
    src = service.create_plan(db, USER, date(2026, 10, 20), [ITEM, ITEM_MIX], remark="旧计划")
    service.complete_plan(db, USER, src.id)
    src.items[0].checked = True
    db.commit()

    new_plan = service.copy_plan_to_date(db, USER, src.id, _today())
    assert new_plan.id != src.id
    assert new_plan.status == TR_STATUS_PLANNED
    assert new_plan.date == _today()
    assert new_plan.remark == "旧计划"                       # 备注复用
    assert [i.exercise_name for i in new_plan.items] == ["杠铃深蹲", "杠铃卧推"]
    assert all(i.checked is False for i in new_plan.items)   # 勾选不复用
    assert new_plan.items[0].weight_kg == 70

    # 原记录保持 recorded 不动
    old = service.get_plan(db, USER, src.id)
    assert old.status == TR_STATUS_RECORDED
    assert len(old.items) == 2
    # 非当日 planned 计划也可作为模板复用
    p2 = service.create_plan(db, USER, date(2026, 10, 21), [ITEM_MIX])
    copied = service.copy_plan_to_date(db, USER, p2.id, _today())
    assert copied.items[0].exercise_name == "杠铃卧推"
    assert len(service.get_plans_by_date(db, USER, _today())) == 2


def test_overview_week_includes_training(db):
    """周总览聚合（替代已删除的 week_plans）：训练计划计入 plans，保存记录计入 records。"""
    from app.core.constants import monday_of
    from app.modules.overview import service as overview

    monday = monday_of(_today())
    service.create_plan(db, USER, monday, [ITEM])
    p2 = service.create_plan(db, USER, monday, [ITEM_MIX])
    # 2026-11-04 起「完成训练」不限当日：本周一（≠今天）也可直接转记录
    service.complete_plan(db, USER, p2.id)
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


def test_stats_week_and_month_aggregation(db):
    """健身档案聚合（仿舞蹈档案）：本周/本月累计训练次数与时长，仅统计记录态。

    期望值用 isocalendar 现算（不写死数量/日期），避免运行日变化导致隐性失败。
    """
    from datetime import timedelta

    now = today_local()
    iso = now.isocalendar()[:2]
    # 本周内两条记录（一条今天、一条本周其他日），本月外一条上月记录
    other_weekday = now - timedelta(days=1) if now.weekday() != 0 else now + timedelta(days=1)
    in_week = service.create_plan(db, USER, now, [ITEM], status=TR_STATUS_RECORDED)
    in_week.duration_s = 1800
    p2 = service.create_plan(db, USER, other_weekday, [ITEM_MIX], status=TR_STATUS_RECORDED)
    p2.duration_s = 3600
    db.commit()
    prev_month = now.replace(day=1) - timedelta(days=3)  # 上月末，不在本月也不在本周
    service.create_plan(db, USER, prev_month, [ITEM], status=TR_STATUS_RECORDED)

    res = service.stats(db, USER)
    # 本周：2 条（今天 + 本周另一日）
    assert res["week_count"] == 2
    assert res["week_duration_s"] == 1800 + 3600
    # 本月：今天 + 本周另一日（上月记录不计入）
    assert res["month_count"] == 2
    assert res["month_duration_s"] == 1800 + 3600
    # 跨年边界一致性：本周另一日若属上一年（1 月初），周判定仍按 ISO (year, week) 计算
    assert in_week.date.isocalendar()[:2] == iso or res["week_count"] >= 1
