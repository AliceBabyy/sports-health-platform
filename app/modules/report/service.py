"""报告服务：周期归一、事实快照、生成、读取、软删除与到期扫描。

生成状态机：generating → ready / failed；同一用户同一周期唯一约束兜底并发。
删除是软删除（status=deleted），扫描任务会跳过 deleted，避免把用户删掉的报告又生成回来。
"""
import hashlib
import json
import logging
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.runtime.invoke import AIServiceError
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.report import ai
from app.modules.report.facts import REPORT_MONTHLY, REPORT_WEEKLY, Period, build_facts, resolve_period
from app.modules.report.models import (
    MODE_AI,
    MODE_RULE,
    REPORT_TYPE_LABELS,
    STATUS_DELETED,
    STATUS_FAILED,
    STATUS_GENERATING,
    STATUS_READY,
    Report,
)
from app.modules.report.schemas import EvidenceItem, ReportNarrative
from config import settings

logger = logging.getLogger(__name__)

GENERATING_STALE_MINUTES = 5


def _hash(facts: dict) -> str:
    """facts 的稳定哈希；剔除随日期变化的 as_of / partial，用于同周期过期检测。"""
    payload = {k: v for k, v in facts.items() if k not in ("as_of", "partial")}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_row(db: Session, user_id: int, period_type: str, period_start: date) -> Report | None:
    return (
        db.query(Report)
        .filter(
            Report.user_id == user_id,
            Report.period_type == period_type,
            Report.period_start == period_start,
        )
        .first()
    )


def _is_stale_generating(row: Report) -> bool:
    if not row.updated_at:
        return True
    return datetime.now() - row.updated_at > timedelta(minutes=GENERATING_STALE_MINUTES)


def _report_payload(row: Report, period: Period, stale: bool = False) -> dict:
    return {
        "id": row.id,
        "type": row.period_type,
        "type_label": REPORT_TYPE_LABELS.get(row.period_type, row.period_type),
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
        "period_label": period.label,
        "status": row.status,
        "mode": row.mode,
        "headline": row.headline,
        "narrative": row.narrative,
        "stale": stale,
        "generated_at": row.generated_at.isoformat(timespec="seconds") if row.generated_at else None,
        "model_name": row.model_name,
        "prompt_version": row.prompt_version,
        "attempts": row.attempts,
        "error": (
            {"code": row.error_code, "message": row.error_message}
            if row.status == STATUS_FAILED
            else None
        ),
    }


def _payload(period: Period, facts: dict, row: Report | None, stale: bool = False) -> dict:
    status = row.status if row and row.status != STATUS_DELETED else ("deleted" if row else "none")
    return {
        "type": period.type,
        "type_label": REPORT_TYPE_LABELS.get(period.type, period.type),
        "period": {
            "type": period.type,
            "label": period.label,
            "start": period.start.isoformat(),
            "end": period.end.isoformat(),
            "as_of": period.as_of.isoformat(),
            "partial": period.partial,
            "range_label": period.range_label,
        },
        "facts": facts,
        "report": _report_payload(row, period, stale) if row and row.status != STATUS_DELETED else None,
        "status": status,
        "stale": stale,
        "auto_enabled": settings.report_auto_enabled,
    }


def read(db: Session, user, period_type: str, anchor: date | None = None, today: date | None = None) -> dict:
    period = resolve_period(period_type, anchor, today)
    if period.start > period.as_of:
        raise AppError(400, "不能查看未来周期的报告")
    facts = build_facts(db, user, period)
    row = _get_row(db, user.id, period.type, period.start)
    stale = bool(row and row.status == STATUS_READY and row.data_hash != _hash(facts))
    return _payload(period, facts, row, stale)


def generate(
    db: Session,
    user,
    period_type: str,
    anchor: date | None = None,
    force: bool = False,
    model_name: str | None = None,
    today: date | None = None,
) -> dict:
    """生成（或复用）一份报告；已 ready 且数据未变时直接返回快照。"""
    period = resolve_period(period_type, anchor, today)
    today = today or date.today()
    if period.start > today:
        raise AppError(400, "不能生成未来周期的报告")
    facts = build_facts(db, user, period)
    facts_hash = _hash(facts)
    row = _get_row(db, user.id, period.type, period.start)

    if row and row.status == STATUS_READY and row.data_hash == facts_hash and not force:
        return _payload(period, facts, row, stale=False)
    if row and row.status == STATUS_DELETED and not force:
        raise AppError(409, "该周期的报告已删除，如需恢复请手动重新生成")
    if row and row.status == STATUS_GENERATING and not _is_stale_generating(row):
        raise AppError(409, "该周期的报告正在生成中，请稍后再试")

    mode = MODE_AI if facts["completeness"]["has_any_record"] else MODE_RULE
    if row is None:
        row = Report(
            user_id=user.id,
            period_type=period.type,
            period_start=period.start,
            period_end=period.end,
            status=STATUS_GENERATING,
            mode=mode,
            facts=facts,
            data_hash=facts_hash,
            attempts=1,
        )
        db.add(row)
    else:
        row.period_end = period.end
        row.status = STATUS_GENERATING
        row.mode = mode
        row.facts = facts
        row.data_hash = facts_hash
        row.attempts = (row.attempts or 0) + 1
        row.deleted_at = None
        row.error_code = None
        row.error_message = None
    try:
        db.commit()
    except IntegrityError:
        # 并发下另一个请求先插入：回滚后按冲突处理
        db.rollback()
        raise AppError(409, "该周期的报告正在生成中，请稍后再试")
    db.refresh(row)

    started = datetime.now()
    if mode == MODE_RULE:
        narrative = _rule_narrative(period, facts)
        meta = {"model": None, "prompt_version": None, "warnings": []}
    else:
        try:
            narrative, meta = ai.generate_narrative(
                period, facts, model_name, cycle_allowed=bool(facts.get("cycle"))
            )
        except AIServiceError as exc:
            row.status = STATUS_FAILED
            row.error_code = "AI_FAILED"
            row.error_message = str(exc)[:500]
            row.generation_ms = int((datetime.now() - started).total_seconds() * 1000)
            db.commit()
            logger.warning("report generation failed: user=%s period=%s/%s err=%s",
                           user.id, period.type, period.start, exc)
            raise AppError(502, f"报告生成失败：{exc}") from exc

    elapsed_ms = int((datetime.now() - started).total_seconds() * 1000)
    row.status = STATUS_READY
    row.narrative = narrative.model_dump(mode="json")
    row.headline = (narrative.headline or "")[:64]
    row.model_name = meta.get("model")
    row.prompt_version = meta.get("prompt_version")
    row.generation_ms = elapsed_ms
    row.generated_at = datetime.now()
    row.error_code = None
    row.error_message = None
    db.commit()
    db.refresh(row)
    return _payload(period, facts, row, stale=False)


def _rule_narrative(period: Period, facts: dict) -> ReportNarrative:
    plans = facts["totals"]["plans"]
    plan_text = (
        f"本期有 {plans} 条计划，但没有一条转为记录。" if plans else "本期没有运动计划，也没有运动记录。"
    )
    compare_label = "上周" if period.type == REPORT_WEEKLY else "上月"
    return ReportNarrative(
        headline="本期暂无运动记录",
        summary=f"{period.label}（{period.range_label}）没有可分析的运动记录。{plan_text}数据为空时不调用模型，等你开始记录后会自动生成完整报告。",
        highlights=[],
        watchouts=[
            EvidenceItem(
                title="记录为空",
                detail=f"没有 recorded 运动，无法计算训练量、强度分布和{compare_label}对比。",
                evidence=[],
            )
        ],
        next_actions=[
            EvidenceItem(
                title="先记录一次",
                detail="可以从 20~30 分钟的低强度训练开始，有记录后报告会自动补齐分析。",
                evidence=[],
            )
        ],
        caveats=["报告只统计 recorded 记录，计划态不计入训练量。", facts["kcal_note"]],
        cycle_note="",
    )


def delete(db: Session, user_id: int, report_id: int) -> dict:
    row = db.query(Report).filter(Report.id == report_id, Report.user_id == user_id).first()
    if row is None:
        raise AppError(404, "报告不存在")
    if row.status == STATUS_DELETED:
        return {"ok": True, "id": row.id}
    row.status = STATUS_DELETED
    row.deleted_at = datetime.now()
    db.commit()
    return {"ok": True, "id": row.id}


def history(
    db: Session,
    user_id: int,
    period_type: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    page = max(1, int(page))
    page_size = max(1, min(50, int(page_size)))
    query = db.query(Report).filter(
        Report.user_id == user_id,
        Report.status != STATUS_DELETED,
    )
    if period_type:
        query = query.filter(Report.period_type == period_type)
    total = query.count()
    rows = (
        query.order_by(Report.period_start.desc(), Report.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = []
    for row in rows:
        period = resolve_period(row.period_type, row.period_start)
        items.append(
            {
                "id": row.id,
                "type": row.period_type,
                "type_label": REPORT_TYPE_LABELS.get(row.period_type, row.period_type),
                "period_start": row.period_start.isoformat(),
                "period_end": row.period_end.isoformat(),
                "period_label": period.label,
                "status": row.status,
                "mode": row.mode,
                "headline": row.headline,
                "generated_at": row.generated_at.isoformat(timespec="seconds") if row.generated_at else None,
            }
        )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def scan_due(db: Session, today: date | None = None, limit: int = 100) -> list[dict]:
    """扫描到期未生成的周期：上周周报 + 上月月报。

    跳过：已 ready、已软删除、生成中未超时、失败但 attempts 已达上限、注册前的周期。
    """
    if not settings.report_auto_enabled:
        return []
    today = today or date.today()
    weekly_anchor = today - timedelta(days=7)
    monthly_anchor = today.replace(day=1) - timedelta(days=1)
    users = db.query(User).filter(User.status == "启用").all()

    tasks = []
    for user in users:
        for period_type, anchor in ((REPORT_WEEKLY, weekly_anchor), (REPORT_MONTHLY, monthly_anchor)):
            period = resolve_period(period_type, anchor, today)
            if period.end > today:
                continue
            if user.created_at and period.end < user.created_at.date():
                continue
            row = _get_row(db, user.id, period_type, period.start)
            refresh = False
            if row:
                if row.status == STATUS_DELETED:
                    continue
                if row.status == STATUS_GENERATING and not _is_stale_generating(row):
                    continue
                if row.status == STATUS_FAILED and (row.attempts or 0) >= settings.report_max_attempts:
                    continue
                if row.status == STATUS_READY:
                    # 用户在周期未结束时手动生成过「进行中」报告：周期结束后必须重写，
                    # 否则月报会永远停留在月中数据（hash 可能没变，force 才能更新叙事）。
                    stored_partial = bool((row.facts or {}).get("partial"))
                    if not (stored_partial and not period.partial):
                        continue
                    refresh = True
            tasks.append(
                {
                    "user_id": user.id,
                    "period_type": period_type,
                    "type_label": REPORT_TYPE_LABELS[period_type],
                    "anchor": period.start.isoformat(),
                    "period_label": period.label,
                    "attempts": row.attempts if row else 0,
                    "status": row.status if row else "none",
                    "refresh": refresh,
                }
            )
            if len(tasks) >= limit:
                return tasks
    return tasks
