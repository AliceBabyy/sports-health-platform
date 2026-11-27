"""每日训练建议单测：事实组装、硬约束、输出清洗、生成状态机、到期扫描与任务表达式。"""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

import models_registry  # noqa: F401
from app.ai.runtime.invoke import AIServiceError
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.cycle.models import PeriodLog, PeriodRecord
from app.modules.daily_advice import ai, facts, service
from app.modules.daily_advice.models import (
    MODE_RULE,
    STATUS_FAILED,
    STATUS_GENERATING,
    STATUS_READY,
    VERDICT_TAGS,
    DailyAdvice as DailyAdviceRow,
    verdict_level,
)
from app.modules.daily_advice.schemas import DailyAdvice
from app.modules.profile import service as profile_service
from app.modules.state_record.models import InflammationRecord, MyalgiaRecord, RecoveryRecord
from app.modules.training import service as training_service
from app.modules.training.schemas import PlanItemIn

TODAY = date(2026, 11, 17)
YESTERDAY = date(2026, 11, 16)
ITEM = PlanItemIn(exercise_name="杠铃深蹲", body_part="腿", weight_kg=70, sets=5, reps="8")


def _user(gender="女", uid=1, age=28):
    return SimpleNamespace(id=uid, gender=gender, age=age)


def _record_fitness(db, user_id=1, day=YESTERDAY):
    plan = training_service.create_plan(db, user_id, day, [ITEM])
    plan.status = "recorded"
    plan.duration_s = 1800
    db.commit()
    return plan


def _advice(**kw):
    data = {
        "verdict": "适合",
        "focus": "上肢推拉 + 轻松有氧",
        "intensity": "高：RPE 7~8，40 分钟",
        "body_parts": ["腿", "臀"],
        "text": (
            "- 今天适合练，但下肢先收着，强度控制在低到中\n"
            "- 上肢推拉加十五分钟轻松有氧，腿和臀今天避开\n"
            "- 最近一次健身在三天前，练的是背和肩\n"
            "- 形体档案提到足弓，练完加三分钟足弓激活\n"
            "- 按这个节奏来，稳稳练就好"
        ),
    }
    data.update(kw)
    return DailyAdvice(**data)


def _fake_meta(**kw):
    return {"model": "fake", "prompt_version": ai.PROMPT_ID, "elapsed_ms": 1, "warnings": []}


# ---------- 事实层 ----------
def test_build_facts_empty(db):
    data = facts.build_facts(db, _user(), TODAY)
    assert data["date"] == TODAY.isoformat()
    assert data["yesterday"]["totals"]["records"] == 0
    assert data["today_records"]["fitness"] == []
    assert data["completeness"]["has_any_record"] is False
    assert data["cycle"] is None
    assert data["hard_limits"] == []


def test_facts_counts_only_recorded_and_lists_plans(db):
    _record_fitness(db)
    training_service.create_plan(db, 1, TODAY, [ITEM])
    data = facts.build_facts(db, _user(), TODAY)
    assert len(data["today_records"]["fitness"]) == 0
    assert len(data["plans_today"]["fitness"]) == 1
    assert data["yesterday"]["totals"]["records"] == 1
    assert data["yesterday"]["totals"]["minutes"] == 30
    assert data["yesterday"]["totals"]["volume"] == 70 * 5 * 8
    assert data["recent_load"]["window_7d"]["records"] == 1
    assert data["recent_load"]["window_30d"] == {
        "records": 1, "fitness": 1, "swim": 0, "dance": 0, "days": 30,
    }
    assert data["recent_load"]["recent_parts_2d"] == ["腿"]  # 昨天练过，今天不再安排


def test_facts_exposes_last_fitness_for_broadcast(db):
    _record_fitness(db)
    data = facts.build_facts(db, _user(), TODAY)
    last = data["recent_load"]["last_fitness"]
    assert last["date"] == YESTERDAY.isoformat()
    assert last["days_ago"] == 1
    assert last["body_parts"] == ["腿"]
    assert last["minutes"] == 30


def test_facts_exposes_recent_advice_for_rotation(db):
    db.add(DailyAdviceRow(
        user_id=1,
        advice_date=YESTERDAY,
        status=STATUS_READY,
        mode="ai",
        verdict="适合：正常练",
        focus="上肢推拉，避开腿",
        intensity="中：RPE 5",
        body_parts=["背"],
        text="- 昨天练上肢\n- 提醒过足弓\n- 鼓励一句",
        facts={},
    ))
    db.commit()
    data = facts.build_facts(db, _user(), TODAY)
    assert data["recent_advice"][0]["date"] == YESTERDAY.isoformat()
    assert "足弓" in data["recent_advice"][0]["text"]


def test_facts_injects_health_profile_qa(db):
    profile_service.save_health_profile_aspect(
        db,
        1,
        "profile_posture",
        [
            {"key": "q1", "aspect": "posture", "label": "足弓情况如何？", "max_length": 120},
            {"key": "q2", "aspect": "posture", "label": "平时久站会累吗？", "max_length": 120},
            {"key": "q3", "aspect": "posture", "label": "最想改善什么体态？", "max_length": 120},
        ],
        {"q1": "足弓偏低，久站会累"},
    )
    data = facts.build_facts(db, _user(), TODAY)
    posture = next(
        item for item in data["profile"]["health_profile"] if item["skill_key"] == "profile_posture"
    )
    assert posture["name"] == "测试-形体矫正"
    assert posture["qa"][0]["group"] == "形体矫正"
    assert "足弓" in posture["qa"][0]["answer"]


def test_cycle_only_for_female_with_records(db):
    db.add(PeriodRecord(user_id=1, start_date=date(2026, 11, 9), end_date=date(2026, 11, 13)))
    db.commit()
    female = facts.build_facts(db, _user("女"), TODAY)
    male = facts.build_facts(db, _user("男"), TODAY)
    assert female["cycle"] is not None
    assert female["cycle"]["cycle_day"] == 9
    assert female["cycle"]["sport_level"]
    assert male["cycle"] is None


def test_hard_limits_muscle_soreness_does_not_cap(db):
    """单纯肌肉酸痛不触发硬约束：前一晚练完次日酸痛是正常训练反应。"""
    db.add(MyalgiaRecord(user_id=1, date=TODAY, star=4))
    db.commit()
    data = facts.build_facts(db, _user(), TODAY)
    assert data["hard_limits"] == []


def test_hard_limits_cycle_pain_caps_intensity_and_blocks_parts(db):
    db.add(PeriodRecord(user_id=1, start_date=TODAY, end_date=TODAY))
    db.commit()
    db.add(PeriodLog(user_id=1, log_date=TODAY, pain_level=3))
    db.commit()
    data = facts.build_facts(db, _user(), TODAY)
    keys = {h["key"] for h in data["hard_limits"]}
    assert "cycle_pain_high" in keys
    pain = next(h for h in data["hard_limits"] if h["key"] == "cycle_pain_high")
    assert pain["cap_intensity"] == "低"
    assert pain["cap_verdict"] == "克制"
    assert pain["block_parts"] is True


def test_hard_limits_cycle_average_caps_at_medium(db):
    db.add(PeriodRecord(user_id=1, start_date=date(2026, 10, 23), end_date=date(2026, 10, 27)))
    db.commit()
    data = facts.build_facts(db, _user(), TODAY)
    keys = {h["key"] for h in data["hard_limits"]}
    assert "cycle_average" in keys
    avg = next(h for h in data["hard_limits"] if h["key"] == "cycle_average")
    assert avg["cap_intensity"] == "中"


def test_hard_limits_recovery_and_inflammation(db):
    db.add(RecoveryRecord(user_id=1, date=TODAY, star=2))
    db.add(InflammationRecord(user_id=1, date=TODAY, star=3))
    db.commit()
    data = facts.build_facts(db, _user(), TODAY)
    limits = {h["key"]: h for h in data["hard_limits"]}
    assert limits["recovery_fair"]["cap_intensity"] == "中"
    assert limits["inflammation_mid"]["cap_intensity"] == "中"

    db.query(RecoveryRecord).delete()
    db.query(InflammationRecord).delete()
    db.add(RecoveryRecord(user_id=1, date=TODAY, star=1))
    db.add(InflammationRecord(user_id=1, date=TODAY, star=4))
    db.commit()
    data = facts.build_facts(db, _user(), TODAY)
    limits = {h["key"]: h for h in data["hard_limits"]}
    assert limits["recovery_low"]["cap_intensity"] == "低"
    assert limits["inflammation_high"]["cap_intensity"] == "低"


def test_hard_limits_no_inflammation_does_not_cap(db):
    """炎症 0 表示没有炎症，0~2 不触发硬约束。"""
    db.add(InflammationRecord(user_id=1, date=TODAY, star=0))
    db.commit()
    data = facts.build_facts(db, _user(), TODAY)
    assert data["hard_limits"] == []


def test_hard_limits_heavy_yesterday(db):
    plan = _record_fitness(db)
    plan.duration_s = 120 * 60
    db.commit()
    data = facts.build_facts(db, _user(), TODAY)
    keys = {h["key"] for h in data["hard_limits"]}
    assert "yesterday_very_heavy" in keys


def test_hard_limits_trained_today(db):
    plan = training_service.create_plan(db, 1, TODAY, [ITEM])
    plan.status = "recorded"
    db.commit()
    data = facts.build_facts(db, _user(), TODAY)
    keys = {h["key"] for h in data["hard_limits"]}
    assert "trained_today" in keys


# ---------- 输出清洗 ----------
def test_schema_accepts_nuanced_fields():
    advice = DailyAdvice(
        verdict="适合但收敛：上肢可以正常练，下肢先减量",
        focus="上肢推拉 + 十五分钟轻松有氧，避开腿和臀",
        intensity="很低：RPE 2，20 分钟，能完整对话",
        body_parts=["背", "肩"],
        text="- 今天适合但收敛：上肢可以正常练，下肢先减量",
    )
    assert advice.verdict.startswith("适合但收敛")
    assert "避开腿和臀" in advice.focus
    assert advice.intensity.startswith("很低")


def test_verdict_level_and_tag_support_nuance():
    assert verdict_level("适合但收敛：下肢先减量") == "适合但收敛"
    assert verdict_level("适合：上肢正常") == "适合"
    assert VERDICT_TAGS[verdict_level("适合但收敛：下肢先减量")] == "average"


def test_sanitize_downgrades_by_hard_limits():
    limits = [
        {"key": "inflammation_high", "cap_intensity": "低", "cap_verdict": None, "block_parts": False},
        {"key": "cycle_pain_high", "cap_verdict": "克制", "cap_intensity": "低", "block_parts": True}
    ]
    cleaned, warnings = ai.sanitize(_advice(focus="无氧"), limits)
    assert cleaned.verdict == "克制"
    assert cleaned.intensity == "低：RPE 7~8，40 分钟"
    assert cleaned.focus == "低强度有氧或恢复：今日不安排力量"
    assert cleaned.body_parts == []
    assert warnings


def test_sanitize_keeps_condition_text_when_capping():
    cleaned, _ = ai.sanitize(
        _advice(verdict="适合：上肢正常", intensity="很高：RPE 9"),
        [{"cap_verdict": "克制", "cap_intensity": "低"}],
    )
    assert cleaned.verdict == "克制：上肢正常"
    assert cleaned.intensity == "低：RPE 9"


def test_sanitize_drops_recently_trained_part():
    cleaned, warnings = ai.sanitize(
        _advice(focus="有氧", body_parts=["腿", "背"]),
        [],
        avoid_parts=["腿"],
    )
    assert cleaned.body_parts == ["背"]
    assert warnings


def test_sanitize_rest_clears_parts():
    cleaned, _ = ai.sanitize(_advice(verdict="休息", focus="有氧", intensity="低"), [])
    assert cleaned.focus.startswith("恢复")
    assert cleaned.body_parts == []


def test_sanitize_recovery_clears_parts():
    cleaned, _ = ai.sanitize(_advice(verdict="克制", focus="恢复"), [])
    assert cleaned.body_parts == []


def test_sanitize_aerobic_keeps_intensity():
    cleaned, _ = ai.sanitize(_advice(focus="有氧", verdict="适合", intensity="中"), [])
    assert cleaned.focus == "有氧"
    assert cleaned.intensity == "中"


def test_sanitize_limits_body_parts_to_two():
    cleaned, _ = ai.sanitize(_advice(body_parts=["腿", "臀", "背", "腿"]), [])
    assert cleaned.body_parts == ["腿", "臀"]


def test_clean_text_truncates_at_sentence():
    long_text = "今天状态一般，" * 12
    text = ai.clean_text(long_text)
    assert len(text) <= ai.MAX_TEXT
    assert "<" not in ai.clean_text("<b>今天</b>可以练")


def test_clean_text_builds_bullet_lines():
    """模型给整段句号句时，服务端拆成每行一句、以「- 」开头、去句末句号。"""
    out = ai.clean_text("今天建议克制，只做低强度活动。臀部仍酸痛，背胸肩先别上重量。")
    assert out.splitlines() == [
        "- 今天建议克制，只做低强度活动",
        "- 臀部仍酸痛，背胸肩先别上重量",
    ]


def test_clean_text_applies_per_line_limits():
    """五句各自按服务端上限收口，第 6 行丢弃。"""
    raw = "\n".join(["甲" * 40, "乙" * 40, "丙" * 60, "丁" * 40, "戊" * 30, "己" * 10])
    lines = ai.clean_text(raw).splitlines()
    assert len(lines) == ai.MAX_LINES == 5
    assert [len(line[2:]) for line in lines] == list(ai.LINE_LIMITS)


def test_clean_text_keeps_existing_bullets_and_limits_lines():
    out = ai.clean_text("- 一行\n- 二行\n- 三行\n- 四行\n- 五行\n- 六行")
    lines = out.splitlines()
    assert len(lines) == ai.MAX_LINES
    assert lines[0] == "- 一行"
    assert all(not line.endswith("。") for line in lines)


# ---------- 生成状态机 ----------
def test_rule_mode_skips_model(db, monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("无记录时不应调用模型")

    monkeypatch.setattr(service.ai, "generate_advice", boom)
    res = service.generate(db, _user(), TODAY)
    assert res["status"] == STATUS_READY
    assert res["mode"] == MODE_RULE
    assert res["text"] == service.RULE_TEXT
    assert res["text"].splitlines()[0].startswith("- ")
    row = db.query(DailyAdviceRow).one()
    assert row.mode == MODE_RULE and row.model_name is None


def test_ai_mode_reuse_same_hash_and_force(db, monkeypatch):
    _record_fitness(db)
    calls = []

    def fake(fact_data, model_name=None):
        calls.append(fact_data["date"])
        return _advice(), _fake_meta()

    monkeypatch.setattr(service.ai, "generate_advice", fake)
    first = service.generate(db, _user(), TODAY)
    assert first["status"] == STATUS_READY and first["tag"] == "good"
    assert len(calls) == 1

    second = service.generate(db, _user(), TODAY)
    assert second["text"] == first["text"] and len(calls) == 1

    # 连点保护：刚生成完的 force 也直接返回旧结果
    third = service.generate(db, _user(), TODAY, force=True)
    assert third["status"] == STATUS_READY and len(calls) == 1

    # 冷却期过后 force 才真正重算
    row = db.query(DailyAdviceRow).one()
    row.generated_at = datetime.now() - timedelta(minutes=5)
    db.commit()
    service.generate(db, _user(), TODAY, force=True)
    assert len(calls) == 2


def test_generation_failure_marks_failed_and_keeps_facts(db, monkeypatch):
    _record_fitness(db)

    def boom(*a, **kw):
        raise AIServiceError("模型服务暂不可用")

    monkeypatch.setattr(service.ai, "generate_advice", boom)
    with pytest.raises(AppError) as exc:
        service.generate(db, _user(), TODAY)
    assert exc.value.status == 502
    row = db.query(DailyAdviceRow).one()
    assert row.status == STATUS_FAILED
    assert row.facts["date"] == TODAY.isoformat()
    assert row.error_code == "AI_FAILED"
    assert row.attempts == 1


def test_generating_row_returns_409(db):
    db.add(
        DailyAdviceRow(
            user_id=1,
            advice_date=TODAY,
            status=STATUS_GENERATING,
            mode="ai",
            facts={"date": TODAY.isoformat()},
            updated_at=datetime.now(),
        )
    )
    db.commit()
    with pytest.raises(AppError) as exc:
        service.generate(db, _user(), TODAY)
    assert exc.value.status == 409


def test_read_empty_payload(db):
    payload = service.read(db, 1, TODAY)
    assert payload["status"] == "none"
    assert payload["text"] is None


# ---------- 到期扫描 ----------
def test_generate_due_respects_switch_and_skips_ready(db, monkeypatch):
    from config import settings

    db.add(User(id=1, username="u", password_hash="x", display_name="U", gender="女", status="启用"))
    db.commit()
    monkeypatch.setattr(settings, "advice_auto_enabled", False)
    assert service.generate_due(db)["scanned"] == 0

    monkeypatch.setattr(settings, "advice_auto_enabled", True)
    monkeypatch.setattr(
        service.ai,
        "generate_advice",
        lambda *a, **kw: (_advice(), _fake_meta()),
    )
    first = service.generate_due(db, day=TODAY)
    assert first["generated"] == 1 and first["failed"] == 0
    second = service.generate_due(db, day=TODAY)
    assert second["generated"] == 0 and second["skipped"] == 1
    assert set(first) == {"day", "scanned", "generated", "skipped", "failed", "items"}


def test_generate_due_limit(db, monkeypatch):
    for uid in (1, 2):
        db.add(User(id=uid, username=f"u{uid}", password_hash="x", display_name="U", gender="女", status="启用"))
    db.commit()
    monkeypatch.setattr(service.ai, "generate_advice", lambda *a, **kw: (_advice(), _fake_meta()))
    result = service.generate_due(db, day=TODAY, limit=1)
    assert result["scanned"] == 1 and result["generated"] == 1


def test_generate_due_skips_failed_at_limit(db, monkeypatch):
    from config import settings

    db.add(User(id=1, username="u", password_hash="x", display_name="U", gender="女", status="启用"))
    db.add(
        DailyAdviceRow(
            user_id=1,
            advice_date=TODAY,
            status=STATUS_FAILED,
            mode="ai",
            facts={"date": TODAY.isoformat()},
            attempts=settings.advice_max_attempts,
        )
    )
    db.commit()
    result = service.generate_due(db, day=TODAY)
    assert result["generated"] == 0 and result["skipped"] == 1


# ---------- 任务注册与接口 ----------
def test_registry_has_daily_advice_jobs():
    from app.modules.system.scheduler.registry import REGISTRY

    spec = REGISTRY["advice.daily"]
    assert spec.default_trigger_type == "cron"
    assert spec.default_trigger_expr == "1 0 * * *"
    assert spec.lock_scope == "advice"
    assert REGISTRY["advice.scan"].default_trigger_type is None
    assert REGISTRY["advice.scan"].lock_scope == "advice"


def test_regenerate_rejects_other_day(db):
    from app.modules.daily_advice.router_api import regenerate_advice
    from app.modules.daily_advice.schemas import AdviceRegenerateIn

    with pytest.raises(AppError) as exc:
        regenerate_advice(payload=AdviceRegenerateIn(date=date(2026, 11, 16)), db=db, user=_user())
    assert exc.value.status == 400


def test_ai_advice_prompt_variables_load():
    from app.ai.prompts.loader import load_prompt

    load_prompt(
        ai.PROMPT_ID,
        today=TODAY.isoformat(),
        weekday="周二",
        cycle_scope=ai.CYCLE_SCOPE_NONE,
    )
