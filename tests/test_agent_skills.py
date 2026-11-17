"""V2.4 技能：定义校验、安全表达式、声明式执行、参数解析与权限。"""
import time
from datetime import date, timedelta

import pytest

from app.core.exceptions import AppError
from app.modules.agent.service import _slash_parts
from app.modules.agent.skills.argument import validate_args
from app.modules.agent.skills.definition import (
    DefinitionInvalid,
    parse_any_definition,
    parse_definition,
    parse_prompt_definition,
)
from app.modules.agent.skills.engine import execute_declarative
from app.modules.agent.skills.execution import execute_skill
from app.modules.agent.skills.management import (
    SkillValidationError,
    create_skill,
    delete_skill,
    latest_version,
    list_skills,
    publish_skill,
    resolved_from_version,
    save_skill,
    set_status,
)
from app.modules.agent.skills.parser import rule_args, time_hint
from app.modules.agent.skills.pending import PendingSkill, PendingStore
from app.modules.agent.skills.platform import LoseWeightIn, run_lose_weight
from app.modules.agent.skills.registry import ResolvedSkill, build_args_model
from app.modules.auth.models import User
from app.modules.body import service as body_service

TODAY = date(2026, 11, 16)


def _definition(**overrides):
    data = {
        "schema_version": 1,
        "params": [
            {"key": "start_date", "type": "date", "required": True, "label": "开始日期"},
            {"key": "end_date", "type": "date", "required": True, "label": "结束日期"},
        ],
        "sources": [
            {"key": "weight", "type": "body_metric", "metric": "weight",
             "range": ["$start_date", "$end_date"]},
        ],
        "steps": [
            {"key": "first", "op": "first", "source": "weight"},
            {"key": "last", "op": "last", "source": "weight"},
            {"key": "count", "op": "count", "source": "weight"},
        ],
        "outputs": [
            {"key": "start", "label": "起始体重", "value": "$first.value", "unit": "kg"},
            {"key": "end", "label": "结束体重", "value": "$last.value", "unit": "kg"},
            {"key": "change", "label": "变化", "value": "$last.value - $first.value", "unit": "kg"},
            {"key": "count", "label": "次数", "value": "$count", "unit": "次"},
        ],
        "summary": "体重由 {start} 变为 {end}，变化 {change}。",
    }
    data.update(overrides)
    return data


def _resolved(definition, key="weight_report"):
    return ResolvedSkill(id=1, key=key, name="体重月报", description="体重变化", category="body",
                        kind="declarative", scope="system", version_no=1, definition=definition)


def _prompt(text="你是一名严格的游泳教练，请指出三个问题并给出计划。"):
    return {"schema_version": 1, "prompt": text}


def test_definition_accepts_minimal_declarative():
    defn = parse_definition(_definition())
    assert len(defn.params) == 2
    assert defn.steps[1].op == "last"


@pytest.mark.parametrize("mutate, fragment", [
    (lambda d: d.update({"sql": "select * from users"}), "不允许的字段"),
    (lambda d: d["params"][0].update({"type": "string"}), "类型仅支持"),
    (lambda d: d["sources"][0].update({"metric": "raw_sql"}), "不在白名单"),
    (lambda d: d["outputs"][0].update({"value": "__import__('os').system('ls')"}), "只允许"),
    (lambda d: d["outputs"][0].update({"value": "$missing.value"}), "不存在"),
    (lambda d: d["steps"][0].update({"field": "value"}), "不支持 field"),
])
def test_definition_rejects_unsafe_or_unknown(mutate, fragment):
    data = _definition()
    mutate(data)
    with pytest.raises(DefinitionInvalid) as exc:
        parse_definition(data)
    assert any(fragment in e["reason"] for e in exc.value.errors)


def test_declarative_engine_computes_outputs(db):
    body_service.upsert_group(db, 1, "basic", date(2026, 11, 1), {"weight": 62.0})
    body_service.upsert_group(db, 1, "basic", date(2026, 11, 10), {"weight": 60.5})
    body_service.upsert_group(db, 1, "basic", date(2026, 11, 15), {"weight": 59.8})

    defn = parse_definition(_definition())
    result = execute_declarative(db, 1, defn, {"start_date": date(2026, 11, 1),
                                               "end_date": date(2026, 11, 16)})
    assert result["status"] == "ok"
    assert result["sample_size"] == 3
    out = {o["key"]: o["value"] for o in result["outputs"]}
    assert out["start"] == 62.0
    assert out["end"] == 59.8
    assert out["change"] == -2.2
    assert out["count"] == 3


def test_declarative_engine_empty_range_is_insufficient(db):
    defn = parse_definition(_definition())
    result = execute_declarative(db, 1, defn, {"start_date": date(2026, 1, 1),
                                               "end_date": date(2026, 1, 31)})
    assert result["status"] == "insufficient_data"
    assert result["sample_size"] == 0
    assert any("没有可用记录" in c for c in result["caveats"])


def test_code_skill_weight_baseline(db):
    body_service.upsert_group(db, 1, "basic", date(2026, 10, 1), {"weight": 63.0})
    body_service.upsert_group(db, 1, "basic", date(2026, 11, 1), {"weight": 61.0})
    body_service.upsert_group(db, 1, "basic", date(2026, 11, 15), {"weight": 60.0})
    result = run_lose_weight(db, 1, LoseWeightIn(start_date=date(2026, 11, 1),
                                                 end_date=date(2026, 11, 16)))
    values = {o["key"]: o["value"] for o in result["outputs"]}
    assert values["baseline_weight"] == 63.0
    assert values["latest_weight"] == 60.0
    assert values["weight_change"] == -3.0
    assert result["sample_size"] == 2


def test_rule_time_hints():
    assert time_hint("这个月", TODAY)[:2] == (date(2026, 11, 1), TODAY)
    assert time_hint("上周", TODAY)[:2] == (date(2026, 11, 9), date(2026, 11, 15))
    assert time_hint("最近两周", TODAY)[2] == 14
    assert time_hint("最近10次", TODAY)[3] == 10
    assert time_hint("最近", TODAY)[4] is True


def test_rule_args_maps_to_declared_params():
    skill = _resolved(_definition())
    args, ambiguous = rule_args(skill, "这个月", TODAY)
    assert args == {"start_date": date(2026, 11, 1), "end_date": TODAY}
    assert ambiguous is False


def test_validate_args_requires_and_normalizes_dates():
    skill = _resolved(_definition())
    args, errors, warnings, missing = validate_args(skill, {}, TODAY)
    assert not errors
    assert set(missing) == {"start_date", "end_date"}

    args, errors, _, missing = validate_args(
        skill, {"start_date": "2026/11/01", "end_date": "2026-11-16"}, TODAY)
    assert not errors and not missing
    assert args["start_date"] == date(2026, 11, 1)


def test_user_prompt_skill_permissions_and_publish(db):
    u1 = User(username="skill_u1", password_hash="x", display_name="u1")
    u2 = User(username="skill_u2", password_hash="x", display_name="u2")
    db.add_all([u1, u2])
    db.commit()

    skill = create_skill(db, u1.id, {
        "name": "体重月报", "key": "weight_report", "slash_alias": "体重月报",
        "description": "体重变化", "category": "body", "kind": "prompt",
        "definition": _prompt("按体重变化给出简要点评。"),
    })
    assert skill.status == "draft"
    assert skill.kind == "prompt"
    publish_skill(db, u1.id, skill.id)
    assert skill.status == "active"
    assert skill.current_version_no == 1

    with pytest.raises(AppError):
        set_status(db, u2.id, skill.id, "disabled")

    version = latest_version(db, skill)
    resolved = resolved_from_version(skill, version)
    assert resolved.kind == "prompt"
    assert list(build_args_model(resolved).model_fields) == []

    owned = [row for row, _ in list_skills(db, u1.id) if row.id == skill.id]
    assert owned and owned[0].scope == "user"
    visible_to_other = [row for row, _ in list_skills(db, u2.id) if row.id == skill.id]
    assert visible_to_other == []

    save_skill(db, u1.id, skill.id, {
        "name": "体重月报二", "key": "weight_report", "slash_alias": "体重月报",
        "description": "体重变化", "category": "body", "kind": "prompt",
        "definition": _prompt("按体重变化给出简要点评。"),
    })
    assert latest_version(db, skill).version_no == 1
    assert skill.current_version_no == 1

    delete_skill(db, u1.id, skill.id)
    assert db.get(type(skill), skill.id) is None


def test_create_skill_rejects_alias_duplicate(db):
    u1 = User(username="skill_dup", password_hash="x", display_name="u1")
    db.add(u1)
    db.commit()
    create_skill(db, u1.id, {"name": "A", "key": "skill_a", "slash_alias": "月报",
                             "description": "", "category": "custom", "kind": "prompt",
                             "definition": _prompt("提示词 A")})
    with pytest.raises(SkillValidationError):
        create_skill(db, u1.id, {"name": "B", "key": "skill_b", "slash_alias": "月报",
                                 "description": "", "category": "custom", "kind": "prompt",
                                 "definition": _prompt("提示词 B")})


def test_slash_parts_supports_fullwidth_space():
    assert _slash_parts("/减重分析 这个月") == ("减重分析", "这个月")
    assert _slash_parts("/减重分析\u3000这个月") == ("减重分析", "这个月")
    assert _slash_parts("/减重分析") == ("减重分析", "")
    assert _slash_parts("减重分析 这个月") is None


def test_pending_store_ttl_and_round_limit():
    store = PendingStore()
    pending = PendingSkill(conversation_id=1, user_id=2, skill_id=3, version_no=1,
                           original_text="/技能 最近", missing=["days_back"])
    store.set(pending)
    assert store.get(1, 2) is pending

    pending.expires_at = time.time() - 1
    assert store.get(1, 2) is None

    store.set(pending)
    assert store.bump(pending) is True
    assert store.bump(pending) is False
    assert store.get(1, 2) is None


def test_user_skill_cannot_shadow_platform(db):
    from app.modules.agent.models import AgentSkill

    u1 = User(username="skill_shadow", password_hash="x", display_name="u1")
    db.add(u1)
    db.add(AgentSkill(scope="system", skill_key="platform_skill", name="平台技能",
                      description="", kind="code", category="body", status="active",
                      current_version_no=1))
    db.commit()
    for payload in (
        {"name": "我的技能", "key": "platform_skill", "slash_alias": None},
        {"name": "平台技能", "key": "my_skill", "slash_alias": None},
        {"name": "我的技能", "key": "my_skill2", "slash_alias": "平台技能"},
    ):
        with pytest.raises(SkillValidationError):
            create_skill(db, u1.id, {**payload, "description": "", "category": "custom",
                                     "kind": "prompt", "definition": _prompt("我的提示词")})


def test_prompt_definition_accepts_and_validates():
    defn = parse_prompt_definition({"schema_version": 1, "prompt": "  你是一名游泳教练。 "})
    assert defn.prompt == "你是一名游泳教练。"

    for bad, fragment in (
        ({"schema_version": 1}, "提示词不能为空"),
        ({"schema_version": 2, "prompt": "x"}, "schema_version"),
        ({"schema_version": True, "prompt": "x"}, "schema_version"),
        ({"schema_version": 1, "prompt": "x", "sql": "select"}, "不允许的字段"),
        ({"schema_version": 1, "prompt": "x" * 4001}, "最多 4000 字"),
    ):
        with pytest.raises(DefinitionInvalid) as exc:
            parse_prompt_definition(bad)
        assert any(fragment in e["reason"] for e in exc.value.errors)

    assert isinstance(parse_any_definition("prompt", {"schema_version": 1, "prompt": "ok"}),
                      type(parse_prompt_definition({"schema_version": 1, "prompt": "ok"})))


def test_prompt_skill_create_publish_and_execute(db):
    from app.modules.agent.models import AgentSkillRun

    u1 = User(username="prompt_u1", password_hash="x", display_name="u1")
    db.add(u1)
    db.commit()

    skill = create_skill(db, u1.id, {
        "name": "教练点评", "key": "coach_review", "slash_alias": "教练",
        "description": "按教练视角点评训练", "category": "custom", "kind": "prompt",
        "definition": {"schema_version": 1, "prompt": "你是一名严格的游泳教练，请指出三个问题并给出计划。"},
    })
    assert skill.kind == "prompt"
    assert skill.status == "draft"

    # 用户技能只能使用提示词类型，草稿期也不允许切换为声明式
    with pytest.raises(SkillValidationError) as draft_switch:
        save_skill(db, u1.id, skill.id, {
            "name": "教练点评", "key": "coach_review", "slash_alias": "教练",
            "description": "按教练视角点评训练", "category": "custom", "kind": "declarative",
            "definition": _definition(),
        })
    assert any(e["field"] == "kind" for e in draft_switch.value.errors)
    assert skill.kind == "prompt"

    publish_skill(db, u1.id, skill.id)
    assert skill.status == "active"
    version = latest_version(db, skill)
    resolved = resolved_from_version(skill, version)
    assert resolved.kind == "prompt"
    assert list(build_args_model(resolved).model_fields) == []
    args, errors, warnings, missing = validate_args(resolved, {}, TODAY)
    assert args == {} and not errors and not missing

    result = execute_skill(db, u1.id, resolved, {}, trigger="test")
    assert result["ok"] is True
    assert result["kind"] == "prompt"
    assert result["outputs"] == []
    assert result["summary"] == "你是一名严格的游泳教练，请指出三个问题并给出计划。"
    runs = db.query(AgentSkillRun).filter(AgentSkillRun.skill_id == skill.id).all()
    assert len(runs) == 1 and runs[0].trigger == "test"

    # 已发布技能同样不允许切换类型
    with pytest.raises(SkillValidationError):
        save_skill(db, u1.id, skill.id, {
            "name": "教练点评", "key": "coach_review", "slash_alias": "教练",
            "description": "按教练视角点评训练", "category": "custom", "kind": "declarative",
            "definition": _definition(),
        })

    delete_skill(db, u1.id, skill.id)
    assert db.get(type(skill), skill.id) is None


def test_user_skill_rejects_declarative_kind(db):
    u1 = User(username="declarative_u1", password_hash="x", display_name="u1")
    db.add(u1)
    db.commit()
    with pytest.raises(SkillValidationError) as exc:
        create_skill(db, u1.id, {
            "name": "体重月报", "key": "weight_report", "slash_alias": "体重月报",
            "description": "体重变化", "category": "body", "kind": "declarative",
            "definition": _definition(),
        })
    assert any(e["field"] == "kind" and "提示词" in e["reason"] for e in exc.value.errors)


def test_platform_declarative_skill_is_readonly_available(db):
    from app.modules.agent.models import AgentSkill, AgentSkillVersion
    from app.modules.agent.skills.registry import available_skills

    skill = AgentSkill(
        scope="system", skill_key="platform_weight_report", name="平台体重月报",
        description="平台声明式体重分析", kind="declarative", category="body",
        status="active", current_version_no=1,
    )
    db.add(skill)
    db.flush()
    db.add(AgentSkillVersion(skill_id=skill.id, version_no=1, definition=_definition(),
                             definition_hash="", created_by=None))
    db.commit()

    available = available_skills(db, 1)
    match = next(item for item in available if item.id == skill.id)
    assert match.kind == "declarative"
    assert list(build_args_model(match).model_fields) == ["start_date", "end_date"]
