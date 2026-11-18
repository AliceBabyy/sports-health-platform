"""健康/运动档案单测：分组题目顺序、合并保存、清空语义与完成判定。"""
import pytest

from app.core.exceptions import AppError
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.profile import service
from app.modules.profile.questions import COMPLETION_MIN_ANSWERS, QUESTION_MAP, grouped_questions


def _make_user(db) -> User:
    user = User(username="hpuser", password_hash=hash_password("pass123456"), display_name="档案用户")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_grouped_questions_keep_definition_order():
    groups = grouped_questions()
    assert [g["name"] for g in groups] == ["目标与节奏", "训练方式与条件", "习惯与限制"]
    assert groups[0]["items"][0]["key"] == "goal"
    assert len([q for g in groups for q in g["items"]]) == len(QUESTION_MAP)


def test_save_creates_row_and_merges_partial_answers(db):
    user = _make_user(db)
    row = service.save_health_profile(db, user, {"goal": "先减到 70 公斤"})
    assert row is not None
    assert row.answers["goal"] == "先减到 70 公斤"

    row = service.save_health_profile(db, user, {"weekly": "3 次左右"})
    assert row.answers["goal"] == "先减到 70 公斤"
    assert row.answers["weekly"] == "3 次左右"
    assert set(row.answers) == {"goal", "weekly"}


def test_empty_string_clears_single_answer(db):
    user = _make_user(db)
    service.save_health_profile(db, user, {"goal": "减脂", "limits": "右膝旧伤"})
    row = service.save_health_profile(db, user, {"limits": "   "})
    assert "limits" not in row.answers
    assert row.answers["goal"] == "减脂"


def test_unknown_key_and_overlong_answer_rejected(db):
    user = _make_user(db)
    with pytest.raises(AppError):
        service.save_health_profile(db, user, {"not_a_question": "x"})
    with pytest.raises(AppError):
        service.save_health_profile(db, user, {"weekly": "3" * 200})


def test_completed_at_requires_minimum_answers(db):
    user = _make_user(db)
    row = service.save_health_profile(db, user, {"goal": "减脂"})
    assert row.completed_at is None

    answers = {key: "答" for key in list(QUESTION_MAP)[:COMPLETION_MIN_ANSWERS]}
    row = service.save_health_profile(db, user, answers)
    assert row.completed_at is not None

    row = service.save_health_profile(db, user, {key: "" for key in list(answers)[:2]})
    assert len(row.answers) == 1
    assert row.completed_at is None


def test_all_answers_cleared_removes_row(db):
    user = _make_user(db)
    row = service.save_health_profile(db, user, {"goal": "增肌"})
    assert row is not None
    result = service.save_health_profile(db, user, {"goal": ""})
    assert result is None
    assert service.get_health_profile(db, user.id) is None


def test_clear_health_profile_and_answers_reader(db):
    user = _make_user(db)
    service.save_health_profile(db, user, {"goal": "塑形", "habits": "晚上练"})
    assert service.get_health_answers(db, user.id) == {"goal": "塑形", "habits": "晚上练"}
    service.clear_health_profile(db, user)
    assert service.get_health_answers(db, user.id) == {}
