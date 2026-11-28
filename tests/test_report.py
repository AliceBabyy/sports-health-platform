"""AI 运动报告单测：周期归一、事实快照、规则/AI 生成、软删除、到期扫描与 evidence 校验。"""
from datetime import date, datetime
from types import SimpleNamespace

import pytest

import models_registry  # noqa: F401
from app.ai.runtime.invoke import AIServiceError
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.cycle.models import PeriodRecord
from app.modules.report import ai, facts, service
from app.modules.report.models import Report, STATUS_DELETED, STATUS_FAILED, STATUS_READY
from app.modules.report.schemas import EvidenceItem, ReportNarrative
from app.modules.training import service as training_service
from app.modules.training.schemas import PlanItemIn

TODAY = date(2026, 11, 17)
LAST_WEEK = date(2026, 11, 9)  # 2026-11-09 周一 ~ 11-15 周日，已结束
ITEM = PlanItemIn(exercise_name="杠铃深蹲", body_part="腿", weight_kg=70, sets=5, reps="8")


def _user(gender="女", uid=1):
    return SimpleNamespace(id=uid, gender=gender)


def _record_fitness(db, user_id=1, day=date(2026, 11, 10)):
    plan = training_service.create_plan(db, user_id, day, [ITEM])
    plan.status = "recorded"
    plan.duration_s = 1800
    plan.calories = 220
    db.commit()
    return plan


def _narrative(**kw):
    data = {
        "headline": "本周训练节奏稳定",
        "summary": "本期完成 1 次训练，共 30 分钟。",
        "highlights": [EvidenceItem(title="训练保持", detail="完成 1 次健身。", evidence=["total.records"])],
        "watchouts": [],
        "next_actions": [EvidenceItem(title="保持频率", detail="下周维持 1 次以上。", evidence=["total.minutes"])],
        "caveats": ["样本量较小。"],
        "cycle_note": "周期数据仅作参考。",
    }
    data.update(kw)
    return ReportNarrative(**data)


# ---------- 周期归一 ----------
def test_resolve_period_week():
    p = facts.resolve_period("weekly", date(2026, 11, 12), today=TODAY)
    assert p.start == date(2026, 11, 9)
    assert p.end == date(2026, 11, 15)
    assert p.partial is False
    assert p.label == "11月9日–11月15日"


def test_resolve_period_month_partial():
    p = facts.resolve_period("monthly", date(2026, 11, 12), today=TODAY)
    assert p.start == date(2026, 11, 1)
    assert p.end == date(2026, 11, 30)
    assert p.as_of == TODAY
    assert p.partial is True


# ---------- 事实快照 ----------
def test_build_facts_empty(db):
    p = facts.resolve_period("weekly", LAST_WEEK, today=TODAY)
    data = facts.build_facts(db, _user(), p)
    assert data["totals"]["records"] == 0
    assert data["completeness"]["has_any_record"] is False
    assert data["cycle"] is None
    assert len(data["cards"]) == 4
    assert data["metrics"]["total.records"]["display"] == "0 次"


def test_build_facts_kcal_scope_excludes_fitness(db):
    _record_fitness(db)
    p = facts.resolve_period("weekly", LAST_WEEK, today=TODAY)
    data = facts.build_facts(db, _user(), p)
    assert data["totals"]["records"] == 1
    assert data["totals"]["minutes"] == 30
    # 健身热量不进总热量（沿用总览口径）
    assert data["totals"]["kcal"] == 0
    assert data["sports"]["fitness"]["calories"] == 220
    assert data["completeness"]["has_any_record"] is True
    assert data["sports"]["fitness"]["top_exercises"][0]["name"] == "杠铃深蹲"


def test_partial_period_compares_same_window(db):
    """进行中周期只对比上期同期天数，避免 17 天 vs 整月造成假涨跌。"""
    _record_fitness(db, day=date(2026, 10, 5))
    _record_fitness(db, day=date(2026, 10, 25))
    period = facts.resolve_period("monthly", date(2026, 11, 1), TODAY)
    data = facts.build_facts(db, _user(), period)
    assert period.partial is True
    assert data["prev_totals"]["records"] == 1
    assert "同期" in data["cards"][0]["delta_text"]
    assert data["metrics"]["prev.records"]["label"] == "上期同期运动次数"


def test_cycle_only_for_female_with_records(db):
    _record_fitness(db)
    db.add(PeriodRecord(user_id=1, start_date=date(2026, 11, 9), end_date=date(2026, 11, 13)))
    db.commit()
    p = facts.resolve_period("weekly", LAST_WEEK, today=TODAY)
    female = facts.build_facts(db, _user("女"), p)
    male = facts.build_facts(db, _user("男"), p)
    unknown = facts.build_facts(db, _user(""), p)
    assert female["cycle"] is not None
    assert female["cycle"]["phase_groups"]
    assert male["cycle"] is None
    assert unknown["cycle"] is None


# ---------- 生成 ----------
def test_generate_empty_uses_rule_mode_without_ai(db, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("空数据不应调用模型")

    monkeypatch.setattr(service.ai, "generate_narrative", boom)
    res = service.generate(db, _user(), "weekly", LAST_WEEK, today=TODAY)
    assert res["report"]["status"] == STATUS_READY
    assert res["report"]["mode"] == "rule"
    assert res["report"]["narrative"]["headline"] == "本期暂无运动记录"
    assert db.query(Report).count() == 1


def test_generate_reuse_and_force(db, monkeypatch):
    _record_fitness(db)
    calls = []

    def fake(period, fact_data, model_name=None, cycle_allowed=False):
        calls.append(period.start)
        return _narrative(), {"model": "fake", "prompt_version": "weekly_report.v1", "warnings": []}

    monkeypatch.setattr(service.ai, "generate_narrative", fake)
    first = service.generate(db, _user(), "weekly", LAST_WEEK, today=TODAY)
    assert first["report"]["status"] == STATUS_READY and len(calls) == 1

    second = service.generate(db, _user(), "weekly", LAST_WEEK, today=TODAY)
    assert second["report"]["id"] == first["report"]["id"] and len(calls) == 1

    service.generate(db, _user(), "weekly", LAST_WEEK, force=True, today=TODAY)
    assert len(calls) == 2


def test_generate_failure_marks_failed_and_keeps_facts(db, monkeypatch):
    _record_fitness(db)

    def boom(*args, **kwargs):
        raise AIServiceError("模型服务暂不可用")

    monkeypatch.setattr(service.ai, "generate_narrative", boom)
    with pytest.raises(AppError) as exc:
        service.generate(db, _user(), "weekly", LAST_WEEK, today=TODAY)
    assert exc.value.status == 502
    row = db.query(Report).one()
    assert row.status == STATUS_FAILED
    assert row.facts["totals"]["records"] == 1
    assert row.error_code == "AI_FAILED"


def test_delete_is_soft_and_blocks_regeneration(db, monkeypatch):
    _record_fitness(db)
    monkeypatch.setattr(
        service.ai, "generate_narrative",
        lambda *a, **kw: (_narrative(), {"model": "fake", "prompt_version": "weekly_report.v1", "warnings": []}),
    )
    res = service.generate(db, _user(), "weekly", LAST_WEEK, today=TODAY)
    rid = res["report"]["id"]
    service.delete(db, 1, rid)
    row = db.query(Report).one()
    assert row.status == STATUS_DELETED and row.deleted_at is not None
    assert service.history(db, 1)["total"] == 0
    with pytest.raises(AppError) as exc:
        service.generate(db, _user(), "weekly", LAST_WEEK, today=TODAY)
    assert exc.value.status == 409


def test_scan_due_skips_ready_and_deleted(db, monkeypatch):
    db.add(User(id=1, username="u", password_hash="x", display_name="U", gender="女",
                status="启用", created_at=datetime(2026, 1, 1)))
    db.commit()
    created = service.scan_due(db, today=TODAY)
    assert {(t["period_type"]) for t in created} == {"weekly", "monthly"}

    monkeypatch.setattr(
        service.ai, "generate_narrative",
        lambda *a, **kw: (_narrative(), {"model": "fake", "prompt_version": "weekly_report.v1", "warnings": []}),
    )
    service.generate(db, _user(), "weekly", LAST_WEEK, today=TODAY)
    after = service.scan_due(db, today=TODAY)
    assert [t["period_type"] for t in after] == ["monthly"]

    service.delete(db, 1, db.query(Report).one().id)
    after_delete = service.scan_due(db, today=TODAY)
    assert all(t["period_type"] != "weekly" for t in after_delete)


def test_scan_due_period_types_filter(db):
    """调度器把周报/月报拆成两条定时任务，扫描必须能按周期类型限定。"""
    db.add(User(id=1, username="u", password_hash="x", display_name="U", gender="女",
                status="启用", created_at=datetime(2026, 1, 1)))
    db.commit()
    weekly = service.scan_due(db, today=TODAY, period_types=("weekly",))
    assert [t["period_type"] for t in weekly] == ["weekly"]
    monthly = service.scan_due(db, today=TODAY, period_types=("monthly",))
    assert [t["period_type"] for t in monthly] == ["monthly"]


def test_generate_due_returns_summary(db, monkeypatch):
    """定时任务与 CLI 共用入口：返回值要能直接写进 job_runs.detail。"""
    db.add(User(id=1, username="u", password_hash="x", display_name="U", gender="女",
                status="启用", created_at=datetime(2026, 1, 1)))
    db.commit()
    monkeypatch.setattr(
        service.ai, "generate_narrative",
        lambda *a, **kw: (_narrative(), {"model": "fake", "prompt_version": "weekly_report.v1", "warnings": []}),
    )
    result = service.generate_due(db, period_types=("weekly",), today=TODAY)
    assert result["scanned"] == 1 and result["generated"] == 1 and result["failed"] == 0
    assert result["items"][0]["status"] == "success"
    assert set(result) == {"scanned", "generated", "failed", "items"}


def test_scan_refreshes_partial_report_after_period_end(db, monkeypatch):
    """周期内手动生成的「进行中」报告，周期结束后必须被扫描重写，否则数据停在半程。"""
    db.add(User(id=1, username="u", password_hash="x", display_name="U", gender="女",
                status="启用", created_at=datetime(2026, 1, 1)))
    db.commit()
    monkeypatch.setattr(
        service.ai, "generate_narrative",
        lambda *a, **kw: (_narrative(), {"model": "fake", "prompt_version": "weekly_report.v1", "warnings": []}),
    )
    _record_fitness(db)
    service.generate(db, _user(), "weekly", LAST_WEEK, today=date(2026, 11, 12))
    tasks = service.scan_due(db, today=TODAY)
    weekly = [t for t in tasks if t["period_type"] == "weekly"]
    assert weekly and weekly[0]["refresh"] is True

    service.generate(db, _user(), "weekly", LAST_WEEK, force=True, today=TODAY)
    tasks = service.scan_due(db, today=TODAY)
    assert all(t["period_type"] != "weekly" for t in tasks)


# ---------- evidence 校验 ----------
def test_sanitize_evidence_filters_and_drops():
    metrics = {"total.records": {"key": "total.records", "label": "运动次数", "display": "3 次"}}
    dirty = _narrative(
        highlights=[
            EvidenceItem(title="保留", detail="d", evidence=["total.records", "fake.key"]),
            EvidenceItem(title="丢弃", detail="d", evidence=["fake.key"]),
        ],
        watchouts=[],
    )
    cleaned, warnings = ai.sanitize_narrative(dirty, metrics)
    assert len(cleaned.highlights) == 1
    assert cleaned.highlights[0].evidence == ["total.records"]
    assert warnings


# 思考开关已从代码内的 qwen* 前缀判断改为 ai_models.extra_body /
# ai_feature_routes.params_override，由 DB 配置驱动；解析与合并见 test_ai_config。
