"""健康档案专项重构测试：轻量结构约束、按专项分套、页面编辑、角色权限。"""
import asyncio
import contextlib
import json
from datetime import datetime

import pytest
from langchain_core.messages import ToolMessage

from app.core.exceptions import AppError
from app.core.security import hash_password
from app.modules.agent.models import AgentSkill, AgentSkillVersion
from app.modules.agent.tools.action_definitions import ACTION_TOOLS, save_health_profile_aspect
from app.modules.agent.tools.policy import TOOL_PERSONA_SCOPES, persona_graph_fingerprint, tools_for_persona
from app.modules.agent.skills.registry import available_skills
from app.modules.auth.models import User
from app.modules.profile import service
from app.modules.profile import skill_runtime
from app.modules.profile.aspect_skills import ASPECT_SKILLS, PROFILE_SKILL_KEYS
from app.modules.profile.questionnaire import MAX_SETS_PER_SKILL, latest_set
from app.modules.profile.questionnaire import normalize_questions


def _user(db, name="aspect_user", gender="女") -> User:
    user = User(
        username=name,
        password_hash=hash_password("pass123456"),
        display_name="档案用户",
        gender=gender,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _questions(labels=None, aspects=None, keys=None):
    labels = labels or ["工作日午餐怎么解决？", "有哪些忌口或过敏？", "晚上会吃夜宵吗？"]
    aspects = aspects or ["diet"] * len(labels)
    keys = keys or [f"q{i + 1}" for i in range(len(labels))]
    return [
        {
            "key": keys[i],
            "aspect": aspects[i],
            "label": label,
            "hint": "",
            "placeholder": "",
            "max_length": 200,
        }
        for i, label in enumerate(labels)
    ]


def _skill_row(db, key="profile_diet", name="测试-饮食档案", alias="饮食档案"):
    skill = AgentSkill(
        scope="system", owner_user_id=None, skill_key=key, name=name,
        description="专项", kind="code", category="profile", status="active",
        current_version_no=1, slash_alias=alias,
    )
    db.add(skill)
    db.flush()
    db.add(AgentSkillVersion(
        skill_id=skill.id, version_no=1,
        definition={"kind": "code", "code_key": key},
        definition_hash="", published_at=datetime.now(),
    ))
    return skill


def test_save_aspect_creates_set_and_reads_back(db):
    user = _user(db)
    result = service.save_health_profile_aspect(
        db, user.id, "profile_diet", _questions(), {"q1": "公司食堂", "q3": "偶尔"}
    )
    assert result["status"] == "created"
    assert result["skill_name"] == "测试-饮食档案"
    assert result["question_count"] == 3
    assert result["answered_count"] == 2

    view = service.get_health_profile(db, user.id)
    assert view is not None
    assert view.filled is True
    assert [item["skill_key"] for item in view.sets] == ["profile_diet"]
    assert view.sets[0]["questions"][0]["answer"] == "公司食堂"
    assert view.sets[0]["questions"][1]["answer"] == ""


def test_aspect_must_belong_to_current_skill(db):
    user = _user(db)
    with pytest.raises(AppError):
        service.save_health_profile_aspect(
            db, user.id, "profile_diet", _questions(aspects=["goal", "diet", "diet"]), {"q1": "x"}
        )
    # 形体专项接受 posture
    posture_questions = _questions(
        ["最想改善哪个体态问题？", "久坐后有没有明显不适？", "每天大概坐多久？"],
        ["posture", "posture", "posture"],
    )
    result = service.save_health_profile_aspect(
        db, user.id, "profile_posture", posture_questions, {"q1": "驼背"}
    )
    assert result["status"] == "created"


def test_exercise_accepts_sport_aspect(db):
    user = _user(db, "exercise_sport_user")
    questions = _questions(
        ["平常主要做哪些运动？", "每周大概练几次？", "平时在哪里练？"],
        ["sport", "training", "environment"],
    )
    result = service.save_health_profile_aspect(
        db, user.id, "profile_exercise", questions, {"q1": "游泳和居家力量"}
    )
    assert result["status"] == "created"
    view = service.get_health_profile(db, user.id)
    latest = view.latest_for("profile_exercise")
    assert latest["questions"][0]["aspect"] == "sport"
    assert latest["questions"][0]["answer"] == "游泳和居家力量"


def test_fitness_skill_accepts_more_questions_and_all_declared_aspects(db):
    user = _user(db, "fitness_skills_user")
    aspects = [
        "goal", "exercise", "sport", "training",
        "environment", "preference", "training", "goal",
    ]
    labels = [f"健身档案问题 {index + 1}？" for index in range(8)]
    result = service.save_health_profile_aspect(
        db, user.id,
        "profile_fitness",
        _questions(labels, aspects),
        {"q1": "先增肌，再改善体能"},
    )
    assert result["status"] == "created"
    assert result["skill_key"] == "profile_fitness"
    view = service.get_health_profile(db, user.id)
    latest = view.latest_for("profile_fitness")
    assert len(latest["questions"]) == 8
    assert {q["aspect"] for q in latest["questions"]} == {
        "goal", "exercise", "sport", "training", "environment", "preference"
    }


def test_question_limit_allows_ten_questions():
    questions = _questions(
        labels=[f"第 {index + 1} 题？" for index in range(10)],
        aspects=["goal"] * 10,
        keys=[f"q{index + 1}" for index in range(10)],
    )
    assert len(normalize_questions(questions, frozenset({"goal"}))) == 10


def test_same_signature_updates_and_different_signature_adds_set(db):
    user = _user(db)
    first = service.save_health_profile_aspect(
        db, user.id, "profile_diet", _questions(), {"q1": "食堂"}
    )
    set_id = first["set_id"]
    updated = service.save_health_profile_aspect(
        db, user.id, "profile_diet", _questions(), {"q1": "食堂", "q2": "不吃辣"}
    )
    assert updated["status"] == "updated"
    assert updated["set_id"] == set_id
    assert updated["answered_count"] == 2

    view = service.get_health_profile(db, user.id)
    assert len(view.all_sets) == 1

    second = service.save_health_profile_aspect(
        db, user.id, "profile_diet",
        _questions(["早餐通常吃什么？", "会喝含糖饮料吗？", "有补充蛋白粉吗？"], ["diet"] * 3),
        {"q1": "包子"},
    )
    assert second["status"] == "created"
    view = service.get_health_profile(db, user.id)
    assert len(view.all_sets) == 2
    assert latest_set(view.all_sets, "profile_diet")["set_id"] == second["set_id"]


def test_max_three_sets_per_skill(db):
    user = _user(db)
    for index in range(4):
        questions = _questions([f"问题 {index}-1？", f"问题 {index}-2？", f"问题 {index}-3？"])
        service.save_health_profile_aspect(
            db, user.id, "profile_diet", questions, {"q1": f"答案 {index}"}
        )
    view = service.get_health_profile(db, user.id)
    diet_sets = [item for item in view.all_sets if item["skill_key"] == "profile_diet"]
    assert len(diet_sets) == MAX_SETS_PER_SKILL
    assert diet_sets[-1]["questions"][0]["label"].startswith("问题 3-1")


def test_questions_and_answers_are_lightly_constrained(db):
    user = _user(db)
    with pytest.raises(AppError):
        service.save_health_profile_aspect(db, user.id, "profile_diet", _questions()[:2], {"q1": "x"})
    with pytest.raises(AppError):
        service.save_health_profile_aspect(db, user.id, "profile_diet", _questions() + _questions(
            labels=["额外 1？", "额外 2？", "额外 3？", "额外 4？", "额外 5？", "额外 6？", "额外 7？", "额外 8？"],
            keys=["q4", "q5", "q6", "q7", "q8", "q9", "q10", "q11"],
        ), {"q1": "x"})
    with pytest.raises(AppError):
        service.save_health_profile_aspect(db, user.id, "profile_diet", _questions(), {})
    with pytest.raises(AppError):
        service.save_health_profile_aspect(db, user.id, "profile_diet", _questions(), {"not_a_key": "x"})
    with pytest.raises(AppError):
        service.save_health_profile_aspect(db, user.id, "profile_diet", _questions(), {"q1": "x" * 201})
    with pytest.raises(AppError):
        service.save_health_profile_aspect(db, user.id, "profile_diet", _questions(), {"q1": ""})


def test_normalize_questions_rejects_duplicate_key_and_label():
    with pytest.raises(ValueError):
        normalize_questions(_questions(keys=["q1", "q1", "q3"]), frozenset({"diet"}))
    with pytest.raises(ValueError):
        normalize_questions(_questions(labels=["同一题？", "同一题？", "第三题？"]), frozenset({"diet"}))
    assert len(normalize_questions(_questions(), frozenset({"diet"}))) == 3


def test_cycle_skill_is_female_only(db):
    male = _user(db, "cycle_male", gender="男")
    with pytest.raises(AppError):
        skill_runtime.run_profile_aspect(db, male.id, "profile_cycle")
    with pytest.raises(AppError):
        service.save_health_profile_aspect(
            db, male.id, "profile_cycle",
            _questions(["周期规律吗？", "经期几天？", "经期会运动吗？"], ["cycle"] * 3),
            {"q1": "不适用"},
        )
    female = _user(db, "cycle_female", gender="女")
    runtime_result = skill_runtime.run_profile_aspect(db, female.id, "profile_cycle")
    assert runtime_result["status"] == "ok"
    assert "生理期" in runtime_result["summary"]
    result = service.save_health_profile_aspect(
        db, female.id, "profile_cycle",
        _questions(["周期规律吗？", "经期几天？", "经期会运动吗？"], ["cycle"] * 3),
        {"q1": "基本规律"},
    )
    assert result["status"] == "created"


def test_page_items_save_and_clear(db):
    user = _user(db)
    service.save_health_profile_aspect(
        db, user.id, "profile_diet", _questions(), {"q1": "食堂"}
    )
    view = service.get_health_profile(db, user.id)
    set_id = view.sets[0]["set_id"]
    service.save_health_profile_items(
        db, user, [{"set_id": set_id, "local_key": "q2", "answer": "不吃辣"}]
    )
    view = service.get_health_profile(db, user.id)
    assert view.sets[0]["questions"][1]["answer"] == "不吃辣"

    service.save_health_profile_items(
        db, user, [{"set_id": set_id, "local_key": "q2", "answer": ""}]
    )
    view = service.get_health_profile(db, user.id)
    assert view.sets[0]["questions"][1]["answer"] == ""

    with pytest.raises(AppError):
        service.save_health_profile_items(
            db, user, [{"set_id": "missing", "local_key": "q1", "answer": "x"}]
        )

    service.clear_health_profile(db, user)
    assert service.get_health_profile(db, user.id) is None


def test_page_set_can_create_edit_and_append_questions(db):
    user = _user(db, "page_set_user")

    def page_questions(labels, aspects=None, answers=None):
        aspects = aspects or ["diet"] * len(labels)
        answers = answers or {}
        return [
            {
                "local_key": f"q{index + 1}",
                "aspect": aspects[index],
                "label": label,
                "hint": "",
                "placeholder": "",
                "max_length": 200,
                "answer": answers.get(f"q{index + 1}", ""),
            }
            for index, label in enumerate(labels)
        ]

    created = service.save_health_profile_page_set(
        db, user, "profile_diet", page_questions(["工作日午餐怎么解决？"], answers={"q1": "食堂"})
    )
    assert created["status"] == "created"
    assert created["question_count"] == 1

    updated = service.save_health_profile_page_set(
        db, user, "profile_diet",
        page_questions(["工作日午餐怎么解决？", "有哪些忌口？"], answers={"q2": "不吃辣"}),
    )
    assert updated["status"] == "updated"
    assert updated["question_count"] == 2
    view = service.get_health_profile(db, user.id)
    assert view.set_count == 1
    assert [q["label"] for q in view.sets[0]["questions"]] == ["工作日午餐怎么解决？", "有哪些忌口？"]

    set_id = view.sets[0]["set_id"]
    service.update_health_profile_page_set(
        db, user, set_id,
        page_questions(["午餐通常怎么解决？", "有哪些忌口？", "晚上吃夜宵吗？"], answers={"q3": "偶尔"}),
    )
    view = service.get_health_profile(db, user.id)
    assert view.sets[0]["questions"][0]["label"] == "午餐通常怎么解决？"
    assert view.sets[0]["questions"][2]["answer"] == "偶尔"

    with pytest.raises(AppError):
        service.save_health_profile_page_set(
            db, user, "profile_diet", page_questions(["a"], ["sleep"])
        )
    with pytest.raises(AppError):
        service.save_health_profile_page_set(
            db, user, "profile_diet",
            [{"local_key": "q2", "aspect": "diet", "label": "b", "max_length": 200}],
        )


def test_profile_info_returns_aspect_questionnaires(db):
    from app.modules.agent.tools import queries

    user = _user(db)
    service.save_health_profile_aspect(db, user.id, "profile_diet", _questions(), {"q1": "食堂"})
    service.save_health_profile_aspect(
        db, user.id, "profile_goal",
        _questions(["主目标是什么？", "希望多久达到？", "最优先改善什么？"], ["goal"] * 3),
        {"q1": "增肌"},
    )
    result = queries.profile_info(db, user.id)
    assert "health_profile" not in result
    assert "custom_health_profile" not in result
    assert len(result["aspect_questionnaires"]) == len(ASPECT_SKILLS)
    assert result["health_profile_meta"]["set_count"] == 2
    diet = next(item for item in result["aspect_questionnaires"] if item["skill_key"] == "profile_diet")
    assert diet["latest"]["qa"][0]["answer"] == "食堂"
    assert diet["latest"]["qa"][1]["answer"] == ""


def test_save_tool_is_scoped_and_writes(db, monkeypatch):
    import app.modules.agent.tools.health_profile_actions as actions

    monkeypatch.setattr(actions, "SessionLocal", lambda: contextlib.nullcontext(db))
    user = _user(db, "tool_user")
    assert "save_health_profile_aspect" in [tool.name for tool in ACTION_TOOLS]
    result = asyncio.run(save_health_profile_aspect.ainvoke(
        {
            "skill_key": "profile_diet",
            "questions": _questions(),
            "answers": {"q1": "工具直接保存"},
        },
        config={"configurable": {"user_id": user.id}},
    ))
    assert result["status"] == "created"
    view = service.get_health_profile(db, user.id)
    assert view.sets[0]["questions"][0]["answer"] == "工具直接保存"


def test_all_aspect_prompts_load_from_shared_file():
    from app.ai.prompts.loader import load_system_prompt

    for aspect in ASPECT_SKILLS:
        text = load_system_prompt(aspect["prompt_id"])
        assert "3~6" in text or "6~10" in text
        assert f"skill_key 固定为 {aspect['key']}" in text


def test_profile_skill_executes_prompt_and_existing_context(db):
    from app.modules.agent.skills.execution import execute_skill

    user = _user(db)
    _skill_row(db, key="profile_goal", name="测试-目标档案", alias="目标档案")
    db.commit()
    resolved = available_skills(
        db, user.id, "health_profile_test", skill_grants=frozenset({"profile_goal"}),
    )[0]
    result = execute_skill(db, user.id, resolved, {"mode": "补齐"}, trigger="slash")
    assert result["ok"] is True
    assert "目标专项" in result["summary"]
    assert "尚无已保存的专项问答" in result["summary"]
    assert "save_health_profile_aspect" in result["summary"]


def test_profile_skills_and_save_tool_are_limited_to_health_profile_test():
    class _FakeTool:
        def __init__(self, name):
            self.name = name

    for key in PROFILE_SKILL_KEYS:
        assert TOOL_PERSONA_SCOPES[f"skill_{key}"] == frozenset({"health_profile_test"})
    assert TOOL_PERSONA_SCOPES["save_health_profile_aspect"] == frozenset({"health_profile_test"})

    tools = [
        _FakeTool("general"),
        _FakeTool("get_profile_info"),
        _FakeTool("save_health_profile_aspect"),
        _FakeTool("skill_profile_diet"),
    ]
    test_role = type("P", (), {
        "key": "health_profile_test",
        "tool_grants": frozenset({"general", "get_profile_info", "save_health_profile_aspect"}),
        "skill_grants": frozenset({"profile_diet"}),
    })
    nutrition = type("P", (), {"key": "nutrition", "tool_grants": None, "skill_grants": None})
    assert [t.name for t in tools_for_persona(tools, test_role)] == [
        "general", "get_profile_info", "save_health_profile_aspect", "skill_profile_diet",
    ]
    assert [t.name for t in tools_for_persona(tools, nutrition)] == ["general", "get_profile_info"]
    assert [t.name for t in tools_for_persona(tools, None)] == ["general", "get_profile_info"]
    explicit = type("P", (), {
        "key": "nutrition",
        "tool_grants": frozenset({"general", "save_health_profile_aspect"}),
        "skill_grants": frozenset({"profile_diet"}),
    })
    assert [t.name for t in tools_for_persona(tools, explicit)] == ["general"]
    assert persona_graph_fingerprint(nutrition) == ""
    assert persona_graph_fingerprint(type("P", (), {"key": "health_profile_test"})).startswith(
        "health_profile_test:"
    )


def test_available_skills_filters_profile_skills_by_persona(db):
    for item in ASPECT_SKILLS:
        _skill_row(db, key=item["key"], name=item["name"], alias=item["slash_alias"])
    db.commit()
    keys = sorted(item.key for item in available_skills(db, 0, "nutrition"))
    assert keys == []
    keys = sorted(item.key for item in available_skills(
        db, 0, "nutrition", skill_grants=frozenset(PROFILE_SKILL_KEYS),
    ))
    assert keys == []
    keys = sorted(item.key for item in available_skills(
        db, 0, "health_profile_test", skill_grants=PROFILE_SKILL_KEYS,
    ))
    assert keys == sorted(PROFILE_SKILL_KEYS)
    keys = sorted(item.key for item in available_skills(db, 0, include_restricted=True))
    assert keys == sorted(PROFILE_SKILL_KEYS)


def test_profile_save_finalizes_and_blocks_new_round():
    from app.modules.agent import graph

    message = ToolMessage(
        content=json.dumps({
            "ok": True,
            "status": "created",
            "skill_name": "测试-饮食档案",
            "question_count": 4,
            "answered_count": 3,
        }, ensure_ascii=False),
        tool_call_id="call_save",
        name="save_health_profile_aspect",
    )
    state = {"messages": [message]}
    assert graph._after_tools(state) == "finalize_profile_save"
    result = graph._finalize_profile_save(state)
    text = result["messages"][0].content
    assert "测试-饮食档案" in text
    assert "共 4 题" in text
    assert "记录 3 题答案" in text
    assert "本轮专项结束" in text
    assert "再来一套" not in text

    other = ToolMessage(
        content='{"ok": true, "status": "created"}',
        tool_call_id="call_other",
        name="get_profile_info",
    )
    assert graph._after_tools({"messages": [other]}) == "agent"


def test_health_profile_test_guard_is_v3_and_only_for_test_role():
    from app.modules.agent.personas.runtime import ResolvedPersona, render_persona_block

    persona = ResolvedPersona(
        id=1, key="health_profile_test", name="健康档案测试", description="",
        scope="system", version_no=1, prompt="旧版角色提示词。",
    )
    block = render_persona_block(persona)
    assert "只做专项" in block
    assert "所有题的 aspect 必须属于当前 skill" in block
    assert "3~10" in block
    assert "至少覆盖 3 个不同 aspect" not in block.replace("旧规则中的“至少覆盖 3 个不同 aspect”", "")

    nutrition = ResolvedPersona(
        id=2, key="nutrition", name="营养师", description="",
        scope="system", version_no=1, prompt="只负责饮食建议。",
    )
    assert "只做专项" not in render_persona_block(nutrition)
