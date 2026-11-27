"""多角色（Persona）数据层、管理、会话绑定与预留接缝测试。"""
import uuid

import pytest

from app.core.exceptions import AppError
from app.modules.agent import service
from app.modules.agent.models import (
    AgentConversation,
    AgentPersona,
    AgentPersonaVersion,
)
from app.modules.agent.personas.definition import (
    PersonaInvalid,
    parse_persona_definition,
    validate_definition,
)
from app.modules.agent.personas.management import (
    PersonaValidationError,
    bindable_persona,
    create_persona,
    delete_persona,
    get_persona,
    save_persona,
    set_status,
)
from app.modules.agent.personas.runtime import (
    DEFAULT_PERSONA_BLOCK,
    render_persona_block,
    resolve_for_conversation,
)
from app.modules.agent.tools import policy
from app.ai.prompts.loader import PROMPTS, load_system_prompt
from app.modules.auth.models import User
from config import settings


def _user(db, username="persona_u1"):
    user = User(username=username, password_hash="x", display_name=username)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _payload(name="我的教练", key="my_coach", prompt="你是用户的训练搭档，关注动作质量。"):
    return {
        "name": name, "key": key, "description": "训练搭档",
        "definition": {"schema_version": 1, "prompt": prompt},
    }


def _create_platform(db, key="nutrition", name="营养师", prompt="你是营养师。"):
    persona = AgentPersona(
        scope="system", owner_user_id=None, persona_key=key, name=name,
        description="平台角色", status="active", current_version_no=1,
    )
    db.add(persona)
    db.flush()
    db.add(AgentPersonaVersion(
        persona_id=persona.id, version_no=1, definition={"schema_version": 1, "prompt": prompt},
        definition_hash="h", published_at=None,
    ))
    db.commit()
    db.refresh(persona)
    return persona


def _bind_conversation(db, user, persona):
    version = db.query(AgentPersonaVersion).filter(
        AgentPersonaVersion.persona_id == persona.id,
        AgentPersonaVersion.version_no == persona.current_version_no,
    ).first()
    row = AgentConversation(
        user_id=user.id, thread_id=uuid.uuid4(), persona_id=persona.id,
        persona_version_no=version.version_no,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_parse_persona_definition_rules(monkeypatch):
    with pytest.raises(PersonaInvalid) as err:
        parse_persona_definition({"schema_version": 1, "prompt": "   "})
    assert err.value.errors[0]["field"] == "prompt"

    with pytest.raises(PersonaInvalid):
        parse_persona_definition({"schema_version": 2, "prompt": "ok"})
    with pytest.raises(PersonaInvalid) as extra:
        parse_persona_definition({"schema_version": 1, "prompt": "ok", "tools": ["x"]})
    assert "tools" in extra.value.errors[0]["reason"]

    monkeypatch.setattr(settings, "agent_persona_max_chars", 5)
    with pytest.raises(PersonaInvalid):
        parse_persona_definition({"schema_version": 1, "prompt": "123456"})

    parsed = parse_persona_definition({"schema_version": 1, "prompt": "  你好  "})
    assert parsed.prompt == "你好"


def test_create_persona_versions_and_quota(db, monkeypatch):
    u1 = _user(db)
    persona = create_persona(db, u1.id, _payload())
    assert persona.scope == "user" and persona.status == "active"
    assert persona.current_version_no == 1

    version = db.query(AgentPersonaVersion).filter_by(persona_id=persona.id, version_no=1).first()
    assert version.published_at is not None

    save_persona(db, u1.id, persona.id, _payload())
    assert persona.current_version_no == 1

    save_persona(db, u1.id, persona.id, _payload(prompt="你是用户的营养搭档。"))
    assert persona.current_version_no == 2
    assert db.query(AgentPersonaVersion).filter_by(persona_id=persona.id).count() == 2

    monkeypatch.setattr(settings, "agent_persona_max_per_user", 1)
    with pytest.raises(PersonaValidationError) as err:
        create_persona(db, u1.id, _payload(name="第二个", key="second"))
    assert any("最多创建" in e["reason"] for e in err.value.errors)


def test_persona_permissions_platform_readonly_and_shadow(db):
    u1 = _user(db, "persona_perm_u1")
    u2 = _user(db, "persona_perm_u2")
    platform = _create_platform(db)

    with pytest.raises(AppError) as readonly:
        set_status(db, u1.id, platform.id, "disabled")
    assert readonly.value.status == 403

    with pytest.raises(AppError) as forbidden:
        get_persona(db, u2.id, create_persona(db, u1.id, _payload()).id)
    assert forbidden.value.status == 403

    with pytest.raises(PersonaValidationError) as shadow:
        create_persona(db, u2.id, _payload(name="营养师", key="nutrition"))
    fields = {e["field"] for e in shadow.value.errors}
    assert {"key", "name"} <= fields


def test_delete_persona_blocks_when_conversation_uses_it(db):
    u1 = _user(db, "persona_del_u1")
    persona = create_persona(db, u1.id, _payload())
    _bind_conversation(db, u1, persona)

    with pytest.raises(AppError) as used:
        delete_persona(db, u1.id, persona.id)
    assert used.value.status == 409

    db.query(AgentConversation).filter(AgentConversation.persona_id == persona.id).delete()
    db.commit()
    delete_persona(db, u1.id, persona.id)
    assert db.get(AgentPersona, persona.id) is None


def test_conversation_binding_snapshot_and_status(db):
    u1 = _user(db, "persona_conv_u1")
    u2 = _user(db, "persona_conv_u2")
    persona = create_persona(db, u1.id, _payload(prompt="版本一人设"))
    conv = _bind_conversation(db, u1, persona)

    resolved = resolve_for_conversation(db, conv, u1.id)
    assert resolved is not None and resolved.version_no == 1
    assert resolved.prompt == "版本一人设"

    save_persona(db, u1.id, persona.id, _payload(prompt="版本二人设"))
    assert persona.current_version_no == 2
    # 老会话固定创建时的版本，不随角色改版漂移
    assert resolve_for_conversation(db, conv, u1.id).prompt == "版本一人设"

    set_status(db, u1.id, persona.id, "disabled")
    with pytest.raises(AppError) as disabled:
        bindable_persona(db, u1.id, persona.id)
    assert disabled.value.status == 400
    # 已绑定会话按快照继续可用
    assert resolve_for_conversation(db, conv, u1.id) is not None

    with pytest.raises(AppError) as foreign:
        bindable_persona(db, u2.id, persona.id)
    assert foreign.value.status == 403


def test_service_create_conversation_carries_persona(db):
    u1 = _user(db, "persona_svc_u1")
    persona = create_persona(db, u1.id, _payload())
    conv = service.create_conversation(db, u1.id, None, persona.id)
    assert conv["kind"] == "persona"
    assert conv["persona_id"] == persona.id
    assert conv["persona_name"] == "我的教练"
    assert conv["persona_version_no"] == 1

    normal = service.create_conversation(db, u1.id, None)
    assert normal["kind"] == "default" and normal["persona_id"] is None


def test_render_persona_block(db):
    assert render_persona_block(None) == DEFAULT_PERSONA_BLOCK

    u1 = _user(db, "persona_block_u1")
    persona = create_persona(db, u1.id, _payload(prompt="训练建议优先看恢复。"))
    resolved = resolve_for_conversation(db, _bind_conversation(db, u1, persona), u1.id)
    block = render_persona_block(resolved)
    assert "我的教练" in block and "v1" in block
    assert "训练建议优先看恢复。" in block


class _FakeTool:
    def __init__(self, name):
        self.name = name


def test_tool_policy_is_noop_now_and_seam_works(monkeypatch):
    tools = [_FakeTool("general"), _FakeTool("diet_only")]
    assert policy.tools_for_persona(tools, "nutrition") == tools
    assert policy.persona_graph_fingerprint(None) == ""

    monkeypatch.setattr(policy, "TOOL_PERSONA_SCOPES", {"diet_only": frozenset({"nutrition"})})
    assert [t.name for t in policy.tools_for_persona(tools, "nutrition")] == ["general", "diet_only"]
    assert [t.name for t in policy.tools_for_persona(tools, "e_trainer")] == ["general"]
    assert [t.name for t in policy.tools_for_persona(tools, None)] == ["general"]
    assert policy.persona_graph_fingerprint(type("P", (), {"key": "nutrition"})) == "nutrition:diet_only"
    assert policy.persona_graph_fingerprint(type("P", (), {"key": "e_trainer"})) == ""


def test_platform_persona_prompts_fit_definition_limit():
    """内置角色必须通过与用户角色相同的定义校验，避免种子写入无法被运行时解析的版本。"""
    for prompt_id in (
        "persona_nutrition.v1",
        "persona_e_trainer.v1",
        "persona_health_profile_test.v3",
    ):
        errors, _ = validate_definition(
            {"schema_version": 1, "prompt": load_system_prompt(prompt_id)}
        )
        assert not errors, f"{prompt_id}: {errors}"


def test_prompt_v8_persona_block_and_v7_removed():
    assert "agent_chat.v6" not in PROMPTS
    assert "agent_chat.v7" not in PROMPTS
    text = load_system_prompt(
        "agent_chat.v8", today="2026-11-18", weekday="周三", now_time="09:00",
        capabilities="只读工具", persona_block="当前角色：营养师（v1）。", run_mode="常规",
    )
    assert "角色设定" in text and "当前角色：营养师（v1）" in text
    assert text.index("规则优先级") > text.index("角色设定")
    assert "本轮模式：常规" in text
    assert "联网搜索" in text


def test_conversation_persona_pair_constraint(db):
    u1 = _user(db, "persona_ck_u1")
    persona = create_persona(db, u1.id, _payload())
    row = AgentConversation(user_id=u1.id, thread_id=uuid.uuid4(), persona_id=persona.id)
    db.add(row)
    with pytest.raises(Exception):
        db.commit()
    db.rollback()

