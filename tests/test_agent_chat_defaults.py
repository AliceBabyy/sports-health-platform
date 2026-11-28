"""通用对话配置：单行默认范围、普通会话 scope 与角色自由授权。"""
from app.modules.agent.chat_defaults import (
    DEFAULT_CHAT_KEY,
    default_chat_dict,
    default_chat_scope,
    get_row,
    save_default_chat,
)
from app.modules.agent.models import AgentSkill, AgentSkillVersion, AgentConversation
from app.modules.agent.router_api import available_skills_api
from app.modules.agent.service import _resolve_chat_scopes
from app.modules.agent.skills.registry import find_by_slash
from app.modules.agent.tools.catalog import tool_names
from app.modules.auth.models import User
from app.modules.system.personas import service


def _skill(db, key="profile_goal", name="测试-目标档案"):
    row = AgentSkill(
        scope="system", skill_key=key, name=name,
        description="目标专项", kind="code", category="profile",
        status="active", current_version_no=1,
    )
    db.add(row)
    db.flush()
    db.add(AgentSkillVersion(
        skill_id=row.id, version_no=1, definition={"schema_version": 1},
        definition_hash="", created_by=None, published_at=None,
    ))
    return row


def _user(db, name="default_chat_user"):
    row = User(username=name, password_hash="x", display_name=name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_default_chat_without_row_means_all_tools_and_skills(db):
    _skill(db)
    db.commit()
    data = default_chat_dict(db)
    assert data["key"] == DEFAULT_CHAT_KEY
    assert data["name"] == "通用对话"
    assert data["tool_grants"] is None and data["skill_grants"] is None
    assert data["tool_count"] == len(tool_names())
    assert data["skill_count"] == 1
    scope = default_chat_scope(db)
    assert scope.key == DEFAULT_CHAT_KEY
    assert scope.tool_grants is None and scope.skill_grants is None


def test_save_default_chat_config_and_scope(db):
    _skill(db)
    db.commit()
    saved = service.save_default_chat_config(db, {
        "tool_grants": ["get_profile_info", "ask_user"],
        "skill_grants": ["profile_goal"],
    }, actor_id=None)
    assert saved["effective_tools"] == ["ask_user", "get_profile_info"]
    assert saved["effective_skills"] == ["profile_goal"]
    row = get_row(db)
    assert row is not None and row.id == 1
    scope = default_chat_scope(db)
    assert scope.tool_grants == frozenset({"get_profile_info", "ask_user"})
    assert scope.skill_grants == frozenset({"profile_goal"})


def test_default_chat_rejects_unknown_and_skill_inside_tool_grants(db):
    _skill(db)
    db.commit()
    for bad in (
        {"tool_grants": ["not_a_tool"]},
        {"tool_grants": ["skill_profile_goal"]},
        {"skill_grants": ["not_a_skill"]},
    ):
        try:
            service.save_default_chat_config(db, bad, actor_id=None)
        except service.PersonaValidationError as exc:
            assert exc.errors
        else:
            raise AssertionError(f"应拒绝非法配置：{bad}")


def test_ordinary_conversation_uses_default_chat_scope(db):
    _skill(db)
    save_default_chat(db, tool_grants=["ask_user"], skill_grants=[], actor_id=None)
    user = _user(db)
    conversation = AgentConversation(
        user_id=user.id, thread_id=__import__("uuid").uuid4(), title="普通会话",
    )
    db.add(conversation)
    db.commit()
    persona, scope = _resolve_chat_scopes(db, conversation, user.id)
    assert persona is None
    assert scope.key == DEFAULT_CHAT_KEY
    assert scope.tool_grants == frozenset({"ask_user"})
    assert scope.skill_grants == frozenset()


def test_normal_chat_slash_uses_default_chat_skill_scope(db):
    _skill(db)
    _skill(db, key="profile_diet", name="测试-饮食档案")
    save_default_chat(db, tool_grants=None, skill_grants=["profile_goal"], actor_id=None)
    user = _user(db, "slash_user")
    scope = default_chat_scope(db)
    found = find_by_slash(
        db, user.id, "profile_goal", scope.key, skill_grants=scope.skill_grants,
    )
    assert found is not None and found.key == "profile_goal"
    assert find_by_slash(
        db, user.id, "profile_diet", scope.key, skill_grants=scope.skill_grants,
    ) is None


def test_available_skills_api_uses_default_chat_scope(db):
    _skill(db)
    _skill(db, key="profile_diet", name="测试-饮食档案")
    save_default_chat(db, tool_grants=None, skill_grants=["profile_goal"], actor_id=None)
    user = _user(db, "api_scope_user")
    data = available_skills_api(persona_id=None, db=db, user=user)
    assert [item["key"] for item in data["list"]] == ["profile_goal"]


def test_page_context_contains_default_chat(db):
    context = service.page_context(db)
    assert context["default_chat"]["key"] == DEFAULT_CHAT_KEY
    assert context["default_chat"]["is_default_chat"] is True
