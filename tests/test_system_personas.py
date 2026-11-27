"""系统内置角色管理：CRUD、版本、工具/技能白名单与运行时过滤。"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import AppError
from app.modules.agent.models import AgentConversation, AgentPersona
from app.modules.agent.personas.management import PersonaValidationError
from app.modules.agent.tools.policy import persona_graph_fingerprint, tools_for_persona
from app.modules.auth.models import User
from app.modules.system.personas import service


def _payload(**overrides):
    data = {
        "key": "admin_test",
        "name": "管理员测试角色",
        "description": "测试内置角色管理",
        "definition": {"schema_version": 1, "prompt": "你是测试角色。"},
        "status": "active",
        "sort_order": 10,
        "tool_grants": ["get_profile_info", "ask_user"],
        "skill_grants": [],
    }
    data.update(overrides)
    return data


def _user(db, username="admin"):
    row = User(username=username, password_hash="x", display_name=username)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_system_persona_rejects_profile_grants_outside_test_role(db):
    from app.modules.agent.models import AgentSkill, AgentSkillVersion

    row = AgentSkill(
        scope="system", skill_key="profile_goal", name="目标档案",
        description="目标专项", kind="code", category="profile",
        status="active", current_version_no=1,
    )
    db.add(row)
    db.flush()
    db.add(AgentSkillVersion(
        skill_id=row.id, version_no=1, definition={"schema_version": 1},
        definition_hash="", created_by=None,
    ))
    db.commit()

    with pytest.raises(PersonaValidationError):
        service.create_system_persona(db, _payload(
            key="nutrition_test", name="营养测试",
            tool_grants=["save_health_profile_aspect"],
        ), None)

    with pytest.raises(PersonaValidationError):
        service.create_system_persona(db, _payload(
            key="nutrition_test", name="营养测试",
            tool_grants=[],
            skill_grants=["profile_goal"],
        ), None)


def test_create_and_list_system_persona(db):
    created = service.create_system_persona(db, _payload(), None)
    assert created["scope"] == "system"
    assert created["key"] == "admin_test"
    assert created["tool_grants"] == ["ask_user", "get_profile_info"]
    assert created["skill_grants"] == []
    assert created["version_no"] == 1
    assert created["published"] is True

    listed = service.list_system_personas(db)
    assert [item["key"] for item in listed] == ["admin_test"]


def test_null_grants_follow_platform_defaults(db):
    created = service.create_system_persona(db, _payload(key="nutrition", tool_grants=None, skill_grants=None), None)
    assert created["tool_grants"] is None
    assert created["skill_grants"] is None
    assert "get_profile_info" in created["effective_tools"]
    assert "save_health_profile_aspect" not in created["effective_tools"]

    granted = service.create_system_persona(db, _payload(
        key="custom_reader", name="自定义读取者",
        tool_grants=["get_profile_info"], skill_grants=[],
    ), None)
    assert granted["effective_tools"] == ["get_profile_info"]
    assert granted["effective_skills"] == []


def test_save_persona_versions_and_key_is_immutable(db):
    created = service.create_system_persona(db, _payload(), None)
    same = service.save_system_persona(db, created["id"], _payload(
        tool_grants=["get_profile_info"],
    ), None)
    assert same["version_no"] == 1
    assert same["tool_grants"] == ["get_profile_info"]

    changed = service.save_system_persona(db, created["id"], _payload(
        definition={"schema_version": 1, "prompt": "你是更新后的测试角色。"},
        tool_grants=["get_profile_info"],
    ), None)
    assert changed["version_no"] == 2

    with pytest.raises(PersonaValidationError) as exc:
        service.save_system_persona(db, created["id"], _payload(key="changed_key"), None)
    assert any(item["field"] == "key" for item in exc.value.errors)


def test_rejects_unknown_tools_and_skills(db):
    with pytest.raises(PersonaValidationError) as exc:
        service.create_system_persona(db, _payload(tool_grants=["not_a_tool"]), None)
    assert any(item["field"] == "tool_grants" for item in exc.value.errors)

    with pytest.raises(PersonaValidationError) as exc:
        service.create_system_persona(db, _payload(skill_grants=["not_a_skill"]), None)
    assert any(item["field"] == "skill_grants" for item in exc.value.errors)


def test_delete_system_persona_rejects_used_role(db):
    created = service.create_system_persona(db, _payload(), None)
    user = _user(db)
    db.add(AgentConversation(
        user_id=user.id, title="角色会话", persona_id=created["id"],
        persona_version_no=created["version_no"], thread_id=uuid4(),
    ))
    db.commit()

    with pytest.raises(AppError) as exc:
        service.delete_system_persona(db, created["id"])
    assert exc.value.status == 409


def test_system_persona_can_grant_restricted_profile_skill(db):
    from app.modules.agent.models import AgentSkill, AgentSkillVersion

    row = AgentSkill(
        scope="system", skill_key="profile_goal", name="目标档案",
        description="目标专项", kind="code", category="profile",
        status="active", current_version_no=1,
    )
    db.add(row)
    db.flush()
    db.add(AgentSkillVersion(
        skill_id=row.id, version_no=1, definition={"schema_version": 1},
        definition_hash="", created_by=None,
    ))
    db.commit()

    created = service.create_system_persona(db, _payload(
        key="health_profile_test", name="档案测试",
        tool_grants=["get_profile_info", "save_health_profile_aspect"],
        skill_grants=["profile_goal"],
    ), None)
    assert created["effective_tools"] == [
        "get_profile_info", "save_health_profile_aspect",
    ]
    assert created["effective_skills"] == ["profile_goal"]

    tools = [
        SimpleNamespace(name="get_profile_info"),
        SimpleNamespace(name="save_health_profile_aspect"),
        SimpleNamespace(name="skill_demo"),
    ]
    persona = SimpleNamespace(
        key="nutrition",
        tool_grants=frozenset({"get_profile_info"}),
        skill_grants=frozenset({"demo"}),
    )
    assert [tool.name for tool in tools_for_persona(tools, persona)] == [
        "get_profile_info", "skill_demo",
    ]
    assert persona_graph_fingerprint(persona).startswith("nutrition:g")

    empty = SimpleNamespace(
        key="nutrition", tool_grants=frozenset(), skill_grants=frozenset(),
    )
    assert tools_for_persona(tools, empty) == []
    assert persona_graph_fingerprint(empty).startswith("nutrition:g")
