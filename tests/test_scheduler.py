"""定时任务单测：表达式解析、参数校验、任务 CRUD、默认补齐、执行记录与失败收敛。"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

import models_registry  # noqa: F401
from app.core.exceptions import AppError
from app.modules.system.scheduler import registry, runner, service, triggers
from app.modules.system.scheduler.models import (
    RUN_FAILED,
    RUN_SUCCESS,
    JobRun,
    ScheduledJob,
)
from app.modules.system.scheduler.registry import JobSpec
from app.modules.system.scheduler.schemas import JobCreateIn, JobUpdateIn

TZ = "Asia/Shanghai"


def _payload(**kw):
    data = {"job_key": "report.weekly", "trigger_type": "cron", "trigger_expr": "0 8 * * mon"}
    data.update(kw)
    return JobCreateIn(**data)


def _bind_sqlite(monkeypatch, db):
    """把 runner 的会话工厂换成测试库，避免连到真实 PostgreSQL。"""
    engine = db.get_bind()
    monkeypatch.setattr(runner, "engine", engine)
    monkeypatch.setattr(
        runner, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False, future=True)
    )


# ---------- 表达式解析 ----------
def test_cron_rejects_numeric_day_of_week():
    """APScheduler 的 day_of_week 以 0=周一，与 crontab 差一位，数字写法必须拒绝。"""
    with pytest.raises(AppError) as exc:
        triggers.parse_trigger("cron", "0 8 * * 1", TZ)
    assert "mon~sun" in exc.value.message


def test_cron_accepts_names_and_sets_timezone():
    trigger = triggers.parse_trigger("cron", "0 8 * * mon", TZ)
    assert str(trigger.timezone) == "Asia/Shanghai"


def test_cron_requires_five_fields():
    with pytest.raises(AppError):
        triggers.parse_trigger("cron", "0 8 * *", TZ)


def test_interval_minimum_and_unit():
    with pytest.raises(AppError):
        triggers.parse_trigger("interval", "30s", TZ)
    trigger = triggers.parse_trigger("interval", "10m", TZ)
    assert trigger.interval.total_seconds() == 600


def test_date_must_be_future():
    with pytest.raises(AppError):
        triggers.parse_trigger("date", "2020-01-01 00:00", TZ)
    future = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    triggers.parse_trigger("date", future, TZ)


def test_unknown_timezone_rejected():
    with pytest.raises(AppError):
        triggers.parse_trigger("cron", "0 8 * * mon", "Mars/Base")


def test_describe_common_forms():
    assert triggers.describe("cron", "0 8 * * mon") == "每周一 08:00"
    assert triggers.describe("cron", "0 8 1 * *") == "每月 1 日 08:00"
    assert triggers.describe("cron", "0 8 * * *") == "每天 08:00"
    assert triggers.describe("interval", "10m") == "每 10 分钟"
    assert triggers.describe("date", "2026-11-20 15:40") == "2026-11-20 15:40 执行一次"


# ---------- 默认任务与 CRUD ----------
def test_seed_defaults_is_idempotent(db):
    assert service.seed_defaults(db) == 3
    assert service.seed_defaults(db) == 0
    assert db.query(ScheduledJob).count() == 3
    keys = {row.job_key for row in db.query(ScheduledJob).all()}
    assert keys == {"report.weekly", "report.monthly", "advice.daily"}


def test_create_job_and_list(db):
    created = service.create_job(db, _payload(name="周一验证"))
    assert created["job_key"] == "report.weekly"
    assert created["trigger_display"] == "每周一 08:00"
    assert created["enabled"] is True
    assert created["next_run_at"] is None  # 调度器未启动时不写时间
    assert service.list_jobs(db)["total"] == 1


def test_create_job_rejects_bad_expression(db):
    with pytest.raises(AppError):
        service.create_job(db, _payload(trigger_expr="0 8 * * 1"))
    assert db.query(ScheduledJob).count() == 0


def test_create_job_rejects_unknown_key(db):
    with pytest.raises(AppError) as exc:
        service.create_job(db, _payload(job_key="nope"))
    assert exc.value.status == 404


def test_update_job_disable(db):
    created = service.create_job(db, _payload())
    row = service.update_job(db, created["id"], JobUpdateIn(enabled=False))
    assert row["enabled"] is False
    assert row["next_run_at"] is None


def test_update_missing_job_returns_404(db):
    with pytest.raises(AppError) as exc:
        service.update_job(db, 999, JobUpdateIn(enabled=False))
    assert exc.value.status == 404


def test_delete_job(db):
    created = service.create_job(db, _payload())
    assert service.delete_job(db, created["id"])["ok"] is True
    assert db.query(ScheduledJob).count() == 0


def test_reconcile_without_scheduler_is_noop(db):
    assert service.reconcile() == 0


def test_mark_missed_records_skipped_run(db, monkeypatch):
    engine = db.get_bind()
    monkeypatch.setattr(
        service, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False, future=True)
    )
    row = ScheduledJob(job_key="report.weekly", name="周报", trigger_type="cron", trigger_expr="0 8 * * mon")
    db.add(row)
    db.commit()

    service.mark_missed(row.id)
    db.expire_all()
    run = db.query(JobRun).one()
    assert run.status == "skipped" and "错过" in run.message
    assert db.get(ScheduledJob, row.id).last_status == "skipped"


# ---------- 执行入口 ----------
def test_runner_records_success(db, monkeypatch):
    _bind_sqlite(monkeypatch, db)
    monkeypatch.setitem(
        registry.REGISTRY,
        "test.echo",
        JobSpec(
            key="test.echo",
            name="回声任务",
            desc="测试用",
            func=lambda session, params: {"scanned": 1, "generated": 1, "failed": 0},
        ),
    )
    row = ScheduledJob(job_key="test.echo", name="回声任务", trigger_type="cron", trigger_expr="0 8 * * mon")
    db.add(row)
    db.commit()

    result = runner.run_task("test.echo", {}, source="manual", job_id=row.id)
    assert result["status"] == RUN_SUCCESS
    assert "生成 1 份" in result["message"]

    db.expire_all()
    run = db.query(JobRun).one()
    assert run.status == RUN_SUCCESS and run.source == "manual"
    job = db.get(ScheduledJob, row.id)
    assert job.run_count == 1 and job.last_status == RUN_SUCCESS


def test_runner_failure_is_recorded(db, monkeypatch):
    _bind_sqlite(monkeypatch, db)

    def _boom(session, params):
        raise RuntimeError("boom")

    monkeypatch.setitem(
        registry.REGISTRY,
        "test.boom",
        JobSpec(key="test.boom", name="失败任务", desc="测试用", func=_boom),
    )
    row = ScheduledJob(job_key="test.boom", name="失败任务", trigger_type="cron", trigger_expr="0 8 * * mon")
    db.add(row)
    db.commit()

    result = runner.run_task("test.boom", {}, source="schedule", job_id=row.id)
    assert result["status"] == RUN_FAILED and "boom" in result["message"]

    db.expire_all()
    assert db.query(JobRun).one().status == RUN_FAILED
    assert db.get(ScheduledJob, row.id).last_status == RUN_FAILED


def test_runner_unknown_key_returns_failed():
    assert runner.run_task("nope.unknown", {})["status"] == RUN_FAILED


def test_runner_rejects_unknown_params(db, monkeypatch):
    _bind_sqlite(monkeypatch, db)
    monkeypatch.setitem(
        registry.REGISTRY,
        "test.strict",
        JobSpec(
            key="test.strict",
            name="严格参数",
            desc="测试用",
            func=lambda session, params: {},
            params_schema=registry.ScanParams,
        ),
    )
    result = runner.run_task("test.strict", {"limit": "abc"})
    assert result["status"] == RUN_FAILED
    assert "参数无效" in result["message"]
