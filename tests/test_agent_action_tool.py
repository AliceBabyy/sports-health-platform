"""AI 助手首个受控写工具单测：动作结构校验、今日 planned 落库、防重复与身份注入。

写工具与只读工具区分：日期固定今天、状态固定 planned，模型无法指定 user_id/日期/状态；
落库复用 training.service.create_plan，不新造写入通道。
"""
import pytest
from pydantic import ValidationError

from app.core.constants import TR_STATUS_PLANNED, today_local
from app.core.exceptions import AppError
from app.modules.agent.tools.action_definitions import (
    PlanItemActionIn,
    SaveTodayPlanIn,
    _user_id,
    save_today_plan,
)
from app.modules.training import service as training_service
from app.modules.training.models import TrainingRecord

U1, U2 = 1, 2


def _item(**kw):
    base = {"exercise_name": "杠铃深蹲", "body_part": "腿", "weight_kg": 70,
            "sets": 5, "reps": "8", "target_weight_kg": 80}
    base.update(kw)
    return PlanItemActionIn(**base)


def _payload(**kw):
    base = {"items": [_item()], "remark": None}
    base.update(kw)
    return SaveTodayPlanIn(**base)


# ---------- 入参结构校验 ----------

def test_item_schema_accepts_valid_and_forbids_extra():
    assert _item().exercise_name == "杠铃深蹲"
    with pytest.raises(ValidationError):
        PlanItemActionIn(exercise_name="x", bogus=1)


def test_item_exercise_name_required_and_bounded():
    with pytest.raises(ValidationError):
        PlanItemActionIn(exercise_name="")
    with pytest.raises(ValidationError):
        PlanItemActionIn(exercise_name="x" * 129)


def test_item_weight_rejects_nan_inf_negative_and_over_limit():
    with pytest.raises(ValidationError):
        PlanItemActionIn(exercise_name="x", weight_kg=float("nan"))
    with pytest.raises(ValidationError):
        PlanItemActionIn(exercise_name="x", weight_kg=float("inf"))
    with pytest.raises(ValidationError):
        PlanItemActionIn(exercise_name="x", weight_kg=-1)
    with pytest.raises(ValidationError):
        PlanItemActionIn(exercise_name="x", weight_kg=1001)


def test_item_sets_range():
    with pytest.raises(ValidationError):
        PlanItemActionIn(exercise_name="x", sets=0)
    with pytest.raises(ValidationError):
        PlanItemActionIn(exercise_name="x", sets=100)
    assert PlanItemActionIn(exercise_name="x", sets=99).sets == 99


def test_payload_requires_at_least_one_item():
    with pytest.raises(ValidationError):
        SaveTodayPlanIn(items=[])


# ---------- 身份注入 ----------

def test_user_id_from_config():
    assert _user_id({"configurable": {"user_id": 7}}) == 7
    with pytest.raises(AppError):
        _user_id(None)
    with pytest.raises(AppError):
        _user_id({"configurable": {}})


# ---------- 落库：今日 planned ----------

def test_save_creates_today_planned_plan(db):
    result = save_today_plan(db, U1, _payload())
    assert result["status"] == "created"
    assert result["date"] == today_local().isoformat()
    assert result["item_count"] == 1

    plan = training_service.get_plan(db, U1, result["plan_id"])
    assert plan.status == TR_STATUS_PLANNED
    assert plan.date == today_local()
    data = training_service.plan_to_dict(plan)
    assert data["items"][0]["exercise_name"] == "杠铃深蹲"
    assert data["items"][0]["weight_kg"] == 70
    assert data["items"][0]["sets"] == 5
    assert data["items"][0]["reps"] == "8"


def test_schema_has_no_date_or_status_fields(db):
    # 入参 schema 没有 date/status/user_id，模型无法指定，日期与状态由代码固定
    fields = set(SaveTodayPlanIn.model_fields)
    assert "date" not in fields and "status" not in fields
    save_today_plan(db, U1, _payload())
    plan = db.query(TrainingRecord).first()
    assert plan.date == today_local() and plan.status == TR_STATUS_PLANNED


# ---------- 防重复 ----------

def test_duplicate_plan_returns_already_exists(db):
    first = save_today_plan(db, U1, _payload())
    second = save_today_plan(db, U1, _payload())
    assert second["status"] == "already_exists"
    assert second["plan_id"] == first["plan_id"]
    assert db.query(TrainingRecord).count() == 1


def test_different_items_create_new_plan(db):
    save_today_plan(db, U1, _payload())
    result = save_today_plan(db, U1, _payload(items=[_item(exercise_name="硬拉")]))
    assert result["status"] == "created"
    assert db.query(TrainingRecord).count() == 2


def test_user_isolation(db):
    save_today_plan(db, U1, _payload())
    # 另一用户的相同计划不被视为重复
    assert save_today_plan(db, U2, _payload())["status"] == "created"
