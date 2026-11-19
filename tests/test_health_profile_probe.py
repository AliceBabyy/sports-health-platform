"""健康档案定制问题单测：问题校验、多套历史、固定题保留、页面合并与角色工具边界。"""
import asyncio
import json

import pytest
from langchain_core.messages import ToolMessage

from app.core.exceptions import AppError
from app.core.security import hash_password
from app.modules.agent.tools.action_definitions import ACTION_TOOLS, save_health_profile_probe
from app.modules.agent.tools.policy import (
    TOOL_PERSONA_SCOPES,
    persona_graph_fingerprint,
    tools_for_persona,
)
from app.modules.auth.models import User
from app.modules.profile import probe, service


def _make_user(db, name="hp_probe_user") -> User:
    user = User(username=name, password_hash=hash_password("pass123456"), display_name="测试用户")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _questions(labels=None):
    labels = labels or ["最近三个月体重变化的主要原因？", "睡眠质量如何？", "训练后恢复情况？"]
    return [
        {
            "key": f"q{i + 1}",
            "group": "本次定制",
            "label": label,
            "hint": "按实际情况写",
            "placeholder": "如：训练量下降",
            "max_length": 200,
        }
        for i, label in enumerate(labels)
    ]


def test_save_probe_creates_set_and_preserves_fixed_answers(db):
    user = _make_user(db)
    service.save_health_profile(db, user, {"goal": "减脂"})
    result = service.save_probe_health_profile(
        db, user.id, _questions(), {"q1": "训练量下降，晚饭变晚", "q2": "经常熬夜"}
    )
    assert result["status"] == "created"
    assert result["question_count"] == 3
    assert result["answered_count"] == 2

    row = service.get_health_profile(db, user.id)
    assert row.answers["goal"] == "减脂"
    assert len(row.custom_questions["sets"]) == 1
    latest = row.custom_questions["sets"][-1]
    assert latest["persona_key"] == "health_profile_test"
    assert latest["questions"][0]["key"].startswith("probe_")
    assert row.answers[latest["questions"][0]["key"]] == "训练量下降，晚饭变晚"


def test_same_question_set_updates_answers_without_new_set(db):
    user = _make_user(db)
    service.save_probe_health_profile(db, user.id, _questions(), {"q1": "第一次回答"})
    result = service.save_probe_health_profile(
        db, user.id, _questions(), {"q1": "第一次回答", "q3": "恢复较慢"}
    )
    assert result["status"] == "updated"
    row = service.get_health_profile(db, user.id)
    assert len(row.custom_questions["sets"]) == 1
    assert result["answered_count"] == 2


def test_duplicate_answers_are_idempotent(db):
    user = _make_user(db)
    service.save_probe_health_profile(db, user.id, _questions(), {"q1": "训练量下降"})
    result = service.save_probe_health_profile(db, user.id, _questions(), {"q1": "训练量下降"})
    assert result["status"] == "already_exists"
    assert len(service.get_health_profile(db, user.id).custom_questions["sets"]) == 1


def test_new_questions_keep_history_and_latest_wins(db):
    user = _make_user(db)
    service.save_probe_health_profile(db, user.id, _questions(), {"q1": "第一套答案"})
    second = _questions(["新的饮食问题？", "新的作息问题？", "新的疼痛问题？"])
    result = service.save_probe_health_profile(db, user.id, second, {"q2": "第二套答案"})
    assert result["status"] == "created"

    row = service.get_health_profile(db, user.id)
    assert len(row.custom_questions["sets"]) == 2
    latest = probe.latest_set(probe.parse_store(row.custom_questions))
    assert latest["questions"][0]["label"] == "新的饮食问题？"
    assert row.answers[latest["questions"][1]["key"]] == "第二套答案"


def test_probe_validation_rejects_bad_payload(db):
    user = _make_user(db)
    with pytest.raises(AppError):
        service.save_probe_health_profile(db, user.id, _questions()[:2], {"q1": "x"})
    with pytest.raises(AppError):
        service.save_probe_health_profile(db, user.id, _questions(), {})
    with pytest.raises(AppError):
        service.save_probe_health_profile(db, user.id, _questions(), {"goal": "覆盖固定题"})
    with pytest.raises(AppError):
        service.save_probe_health_profile(db, user.id, _questions(), {"q1": "x" * 201})


def test_page_save_accepts_custom_key_and_clears_it(db):
    user = _make_user(db)
    service.save_probe_health_profile(db, user.id, _questions(), {"q1": "页面答案"})
    row = service.get_health_profile(db, user.id)
    key = row.custom_questions["sets"][-1]["questions"][0]["key"]
    assert key.startswith("probe_")

    row = service.save_health_profile(db, user, {key: "改过的页面答案"})
    assert row.answers[key] == "改过的页面答案"

    row = service.save_health_profile(db, user, {key: "", "goal": "减脂"})
    assert key not in row.answers
    assert row.answers["goal"] == "减脂"


def test_profile_info_returns_all_health_profile_history(db):
    from app.modules.agent.tools import queries

    user = _make_user(db, "hp_probe_history_user")
    service.save_health_profile(db, user, {"goal": "减脂"})
    service.save_probe_health_profile(db, user.id, _questions(), {"q1": "旧答案"})
    second = _questions(["新的饮食问题？", "新的作息问题？", "新的疼痛问题？"])
    service.save_probe_health_profile(db, user.id, second, {"q2": "新答案"})

    result = queries.profile_info(db, user.id)
    assert result["health_profile"] == {"goal": "减脂"}
    assert result["health_profile_meta"]["filled"] is True
    assert result["health_profile_meta"]["custom_set_count"] == 2
    assert len(result["custom_health_profile_history"]) == 2

    newest, older = result["custom_health_profile_history"]
    assert newest["qa"][0]["label"] == "新的饮食问题？"
    assert newest["qa"][1]["answer"] == "新答案"
    assert newest["answered_count"] == 1
    assert older["qa"][0]["answer"] == "旧答案"
    assert older["qa"][1]["answer"] == ""
    assert result["custom_health_profile"][0]["label"] == "新的作息问题？"
    assert result["custom_health_profile_history"][0]["qa"][0]["group"] == "本次定制"
    assert result["custom_health_profile_group_coverage"] == [
        {"group": "本次定制", "question_count": 6, "set_count": 2}
    ]


def test_special_tool_is_bound_to_health_profile_test_only(db, monkeypatch):
    import contextlib

    from app.modules.agent.tools import health_profile_actions

    monkeypatch.setattr(health_profile_actions, "SessionLocal", lambda: contextlib.nullcontext(db))
    user = _make_user(db, "hp_probe_tool_user")
    assert "save_health_profile_probe" in [tool.name for tool in ACTION_TOOLS]
    result = asyncio.run(save_health_profile_probe.ainvoke(
        {"questions": _questions(), "answers": {"q1": "工具直接保存"}},
        config={"configurable": {"user_id": user.id}},
    ))
    assert result["status"] == "created"
    row = service.get_health_profile(db, user.id)
    assert row.answers[row.custom_questions["sets"][-1]["questions"][0]["key"]] == "工具直接保存"


def test_scope_only_health_profile_test_and_fingerprint():
    class _FakeTool:
        def __init__(self, name):
            self.name = name

    tools = [_FakeTool("general"), _FakeTool("save_health_profile_probe")]
    assert TOOL_PERSONA_SCOPES["save_health_profile_probe"] == frozenset({"health_profile_test"})
    assert [t.name for t in tools_for_persona(tools, "health_profile_test")] == [
        "general", "save_health_profile_probe"
    ]
    assert [t.name for t in tools_for_persona(tools, "nutrition")] == ["general"]
    assert [t.name for t in tools_for_persona(tools, None)] == ["general"]
    assert persona_graph_fingerprint(type("P", (), {"key": "health_profile_test"})).startswith(
        "health_profile_test:"
    )
    assert persona_graph_fingerprint(type("P", (), {"key": "nutrition"})) == ""


def test_probe_save_finalizes_and_blocks_new_round():
    from app.modules.agent import graph

    payload = {
        "ok": True,
        "status": "created",
        "question_count": 7,
        "answered_count": 6,
    }
    message = ToolMessage(
        content=json.dumps(payload, ensure_ascii=False),
        tool_call_id="call_save",
        name="save_health_profile_probe",
    )
    state = {"messages": [message]}
    assert graph._after_tools(state) == "finalize_probe_save"

    result = graph._finalize_probe_save(state)
    text = result["messages"][0].content
    assert "共 7 题" in text
    assert "记录 6 题答案" in text
    assert "本轮健康档案测试结束" in text
    assert "再来一套" in text

    other = ToolMessage(
        content='{"ok": true, "status": "created"}',
        tool_call_id="call_other",
        name="get_profile_info",
    )
    assert graph._after_tools({"messages": [other]}) == "agent"


def test_health_profile_test_persona_block_always_has_guard():
    from app.modules.agent.personas.runtime import ResolvedPersona, render_persona_block

    persona = ResolvedPersona(
        id=1, key="health_profile_test", name="健康档案测试", description="",
        scope="system", version_no=1, prompt="旧版角色提示词，不含新的覆盖规则。",
    )
    block = render_persona_block(persona)
    assert "至少覆盖 3 个不同主题" in block
    assert "同一主题最多 2 题" in block
    assert "保存成功后本轮立即结束" in block

    nutrition = ResolvedPersona(
        id=2, key="nutrition", name="营养师", description="",
        scope="system", version_no=1, prompt="只负责饮食建议。",
    )
    assert "至少覆盖 3 个不同主题" not in render_persona_block(nutrition)
