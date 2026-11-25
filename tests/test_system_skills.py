"""系统内置技能管理：声明式 CRUD/版本、代码技能只读、引用保护、试运行与运行记录。"""
from datetime import date, datetime

import pytest

from app.core.exceptions import AppError
from app.modules.agent.models import AgentPersona, AgentSkill, AgentSkillRun, AgentSkillVersion
from app.modules.agent.skills.management import SkillValidationError
from app.modules.agent.skills.registry import available_skills
from app.modules.auth.models import User
from app.modules.body.models import BodyBasicRecord
from app.modules.system.skills import service


def _definition(**overrides):
    definition = {
        "schema_version": 1,
        "params": [
            {"key": "start_date", "type": "date", "required": False, "label": "开始日期"},
            {"key": "end_date", "type": "date", "required": False, "label": "结束日期"},
        ],
        "sources": [
            {"key": "weight", "type": "body_metric", "metric": "weight",
             "range": ["$start_date", "$end_date"]},
        ],
        "steps": [
            {"key": "avg_weight", "op": "avg", "source": "weight", "field": "value"},
        ],
        "outputs": [
            {"key": "avg", "label": "平均体重", "value": "$avg_weight", "unit": "kg"},
        ],
        "summary": "平均体重 {avg}。",
    }
    definition.update(overrides)
    return definition


def _payload(**overrides):
    data = {
        "key": "weight_month",
        "name": "体重月报",
        "slash_alias": "体重月报",
        "description": "按月查看平均体重",
        "category": "body",
        "kind": "declarative",
        "status": "active",
        "definition": _definition(),
    }
    data.update(overrides)
    return data


def _user(db, username="admin"):
    row = User(username=username, password_hash="x", display_name=username)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _code_skill(db, key="lose_weight_analyse", name="减重分析"):
    row = AgentSkill(
        scope="system", owner_user_id=None, skill_key=key, name=name,
        description="代码技能", kind="code", category="body",
        status="active", current_version_no=1,
    )
    db.add(row)
    db.flush()
    db.add(AgentSkillVersion(
        skill_id=row.id, version_no=1,
        definition={"kind": "code", "code_key": key},
        definition_hash="", published_at=datetime.now(),
    ))
    db.commit()
    db.refresh(row)
    return row


def test_create_and_list_system_skill(db):
    created = service.create_system_skill(db, _payload(), None)
    assert created["scope"] == "system"
    assert created["kind"] == "declarative"
    assert created["key"] == "weight_month"
    assert created["tool_name"] == "skill_weight_month"
    assert created["version_no"] == 1
    assert created["published"] is True
    assert created["can_edit"] is True
    assert created["can_delete"] is True

    listed = service.list_system_skills(db)
    assert [item["key"] for item in listed] == ["weight_month"]
    assert service.get_system_skill(db, created["id"])["name"] == "体重月报"


def test_create_rejects_code_kind_and_invalid_dsl(db):
    with pytest.raises(SkillValidationError) as exc:
        service.create_system_skill(db, _payload(kind="code"), None)
    assert any(item["field"] == "kind" for item in exc.value.errors)

    with pytest.raises(SkillValidationError) as exc:
        service.create_system_skill(db, _payload(key="lose_weight_analyse"), None)
    assert any(item["field"] == "key" for item in exc.value.errors)

    bad = _definition(sources=[{"key": "weight", "type": "unknown_source"}])
    with pytest.raises(SkillValidationError) as exc:
        service.create_system_skill(db, _payload(definition=bad), None)
    assert any(item["field"].startswith("sources") for item in exc.value.errors)


def test_platform_key_name_and_alias_are_unique(db):
    service.create_system_skill(db, _payload(), None)
    for field, overrides in (
        ("key", {"key": "weight_month"}),
        ("name", {"name": "体重月报"}),
        ("slash_alias", {"slash_alias": "体重月报"}),
    ):
        with pytest.raises(SkillValidationError) as exc:
            service.create_system_skill(db, _payload(**overrides), None)
        assert any(item["field"] == field for item in exc.value.errors)


def test_save_versions_only_when_definition_changes(db):
    created = service.create_system_skill(db, _payload(), None)
    same = service.save_system_skill(db, created["id"], _payload(
        description="只改描述", definition=_definition(),
    ), None)
    assert same["version_no"] == 1
    assert same["description"] == "只改描述"

    changed = service.save_system_skill(db, created["id"], _payload(
        description="只改描述",
        definition=_definition(summary="本期平均体重 {avg}。"),
    ), None)
    assert changed["version_no"] == 2
    assert changed["current_version_no"] == 2

    with pytest.raises(SkillValidationError) as exc:
        service.save_system_skill(db, created["id"], _payload(key="another_key"), None)
    assert any(item["field"] == "key" for item in exc.value.errors)


def test_code_skill_is_read_only_but_can_toggle_status(db):
    skill = _code_skill(db)
    with pytest.raises(AppError) as exc:
        service.save_system_skill(db, skill.id, _payload(name="改不了"), None)
    assert exc.value.status == 400

    disabled = service.set_system_skill_status(db, skill.id, "disabled")
    assert disabled["status"] == "disabled"
    assert available_skills(db, 0) == []

    with pytest.raises(AppError) as exc:
        service.delete_system_skill(db, skill.id)
    assert exc.value.status == 400


def test_delete_rejects_persona_reference(db):
    created = service.create_system_skill(db, _payload(), None)
    db.add(AgentPersona(
        scope="system", persona_key="nutrition_test", name="营养师测试",
        skill_grants=[created["key"]],
    ))
    db.commit()

    with pytest.raises(AppError) as exc:
        service.delete_system_skill(db, created["id"])
    assert exc.value.status == 409

    db.query(AgentPersona).delete()
    db.commit()
    service.delete_system_skill(db, created["id"])
    assert service.list_system_skills(db) == []


def test_validate_definition_endpoint_payload(db):
    assert service.validate_definition(_definition()) == {"ok": True, "errors": [], "warnings": []}
    bad = _definition(outputs=[{"key": "avg", "label": "平均", "value": "import os"}])
    result = service.validate_definition(bad)
    assert result["ok"] is False
    assert result["errors"]


def test_test_run_records_audit_and_lists_runs(db):
    user = _user(db)
    db.add(BodyBasicRecord(user_id=user.id, record_date=date(2026, 11, 20), weight_kg=70))
    db.commit()
    created = service.create_system_skill(db, _payload(), None)

    result = service.test_system_skill(db, user.id, created["id"], {})
    assert result["status"] == "ok"
    assert result["skill"] == "weight_month"
    assert result["summary"] == "平均体重 70kg。"
    assert result["sample_size"] == 1

    runs = service.list_platform_runs(db, created["id"])
    assert len(runs) == 1
    assert runs[0].trigger == "test"
    assert runs[0].status == "ok"


def test_test_run_invalid_args_does_not_write_run(db):
    user = _user(db)
    created = service.create_system_skill(db, _payload(), None)
    result = service.test_system_skill(db, user.id, created["id"], {"start_date": "不是日期"})
    assert result["ok"] is False
    assert result["status"] == "invalid_args"
    assert service.list_platform_runs(db, created["id"]) == []


def test_platform_skill_run_list_includes_other_users(db):
    user_a = _user(db, "a")
    user_b = _user(db, "b")
    created = service.create_system_skill(db, _payload(), None)
    for user in (user_a, user_b):
        db.add(AgentSkillRun(
            skill_id=created["id"], version_no=1, user_id=user.id,
            trigger="model", status="ok", sample_size=1, duration_ms=10,
        ))
    db.commit()
    assert len(service.list_platform_runs(db, created["id"])) == 2


def test_refresh_system_graph_rebuilds_and_clears_user_cache(monkeypatch):
    from app.modules.agent import runtime as agent_runtime

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    new_graph = object()
    monkeypatch.setattr(agent_runtime, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(agent_runtime, "available_skills", lambda db, user_id: [])
    monkeypatch.setattr(agent_runtime, "build_user_graph", lambda saver, skills: new_graph)
    runtime = {
        "saver": object(), "graph": "old", "system_graph": "old",
        "graphs": {("user", "fingerprint"): "cached"},
    }
    agent_runtime.refresh_system_graph(runtime)
    assert runtime["system_graph"] is new_graph
    assert runtime["graph"] is new_graph
    assert runtime["graphs"] == {}
