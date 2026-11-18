"""每日训练建议服务：生成状态机、同日复用、到期生成与侧栏读取。

状态机：generating → ready / failed；同一用户同一天唯一约束兜底并发。
不设软删除：侧栏只展示当天一条，定时任务按「当天已 ready 即跳过」保证幂等。
"""
import hashlib
import json
import logging
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.runtime.invoke import AIServiceError
from app.core.constants import today_local
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.daily_advice import ai
from app.modules.daily_advice.facts import build_facts
from app.modules.daily_advice.models import (
    INTENSITY_LOW,
    MODE_AI,
    MODE_RULE,
    STATUS_FAILED,
    STATUS_GENERATING,
    STATUS_READY,
    VERDICT_SUITABLE,
    VERDICT_TAGS,
    DailyAdvice as DailyAdviceRow,
)
from app.modules.daily_advice.schemas import DailyAdvice
from config import settings

logger = logging.getLogger(__name__)

GENERATING_STALE_MINUTES = 5
# 手动刷新连点保护：同一行在该窗口内不重复调模型
MANUAL_REUSE_SECONDS = 60

RULE_TEXT = "- 数据还少，先快走 20~30 分钟\n- 开始记录后建议会更贴合你"


def data_hash(facts: dict) -> str:
    """facts 的稳定哈希：用于判断同一天的数据是否变化。"""
    raw = json.dumps(facts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_row(db: Session, user_id: int, day: date) -> DailyAdviceRow | None:
    return (
        db.query(DailyAdviceRow)
        .filter(DailyAdviceRow.user_id == user_id, DailyAdviceRow.advice_date == day)
        .first()
    )


def _is_stale_generating(row: DailyAdviceRow) -> bool:
    if not row.updated_at:
        return True
    return datetime.now() - row.updated_at > timedelta(minutes=GENERATING_STALE_MINUTES)


def _empty_payload(day: date) -> dict:
    return {
        "date": day.isoformat(),
        "status": "none",
        "mode": None,
        "verdict": None,
        "focus": None,
        "intensity": None,
        "body_parts": [],
        "text": None,
        "tag": None,
        "generated_at": None,
        "error": None,
    }


def _payload(row: DailyAdviceRow) -> dict:
    return {
        "date": row.advice_date.isoformat(),
        "status": row.status,
        "mode": row.mode,
        "verdict": row.verdict,
        "focus": row.focus,
        "intensity": row.intensity,
        "body_parts": list(row.body_parts or []),
        "text": row.text,
        "tag": VERDICT_TAGS.get(row.verdict),
        "generated_at": row.generated_at.isoformat(timespec="seconds") if row.generated_at else None,
        "error": (
            {"code": row.error_code, "message": row.error_message}
            if row.status == STATUS_FAILED
            else None
        ),
    }


def read(db: Session, user_id: int, day: date | None = None) -> dict:
    """读取某天的建议；无行返回 status=none 的轻量结构。"""
    day = day or today_local()
    row = _get_row(db, user_id, day)
    return _payload(row) if row else _empty_payload(day)


def _rule_advice() -> DailyAdvice:
    """无任何可用数据时的固定文案：不调模型。"""
    return DailyAdvice(
        verdict=VERDICT_SUITABLE,
        focus="有氧",
        intensity=INTENSITY_LOW,
        body_parts=[],
        text=RULE_TEXT,
    )


def generate(
    db: Session,
    user,
    day: date | None = None,
    force: bool = False,
    model_name: str | None = None,
) -> dict:
    """生成（或复用）当天的一份建议；已 ready 且数据未变时直接返回。"""
    day = day or today_local()
    facts = build_facts(db, user, day)
    facts_hash = data_hash(facts)
    row = _get_row(db, user.id, day)

    if row and row.status == STATUS_READY and row.data_hash == facts_hash and not force:
        return _payload(row)
    if (
        row
        and row.status == STATUS_READY
        and force
        and row.generated_at
        and (datetime.now() - row.generated_at).total_seconds() < MANUAL_REUSE_SECONDS
    ):
        return _payload(row)
    if row and row.status == STATUS_GENERATING and not _is_stale_generating(row):
        raise AppError(409, "今日建议正在生成中，请稍后再试")

    mode = MODE_AI if facts["completeness"]["has_any_record"] else MODE_RULE
    if row is None:
        row = DailyAdviceRow(
            user_id=user.id,
            advice_date=day,
            status=STATUS_GENERATING,
            mode=mode,
            facts=facts,
            data_hash=facts_hash,
            attempts=1,
        )
        db.add(row)
    else:
        row.status = STATUS_GENERATING
        row.mode = mode
        row.facts = facts
        row.data_hash = facts_hash
        row.attempts = (row.attempts or 0) + 1
        row.error_code = None
        row.error_message = None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "今日建议正在生成中，请稍后再试") from None
    db.refresh(row)

    started = datetime.now()
    if mode == MODE_RULE:
        advice = _rule_advice()
        meta = {"model": None, "prompt_version": None, "warnings": []}
    else:
        try:
            advice, meta = ai.generate_advice(facts, model_name)
        except AIServiceError as exc:
            row.status = STATUS_FAILED
            row.error_code = "AI_FAILED"
            row.error_message = str(exc)[:500]
            row.generation_ms = int((datetime.now() - started).total_seconds() * 1000)
            db.commit()
            logger.warning(
                "daily advice generation failed: user=%s day=%s err=%s", user.id, day, exc
            )
            raise AppError(502, f"今日建议生成失败：{exc}") from exc

    row.status = STATUS_READY
    row.mode = mode
    row.verdict = advice.verdict
    row.focus = advice.focus
    row.intensity = advice.intensity
    row.body_parts = advice.body_parts
    row.text = advice.text[:200]
    row.model_name = meta.get("model")
    row.prompt_version = meta.get("prompt_version")
    row.generation_ms = int((datetime.now() - started).total_seconds() * 1000)
    row.generated_at = datetime.now()
    row.error_code = None
    row.error_message = None
    db.commit()
    db.refresh(row)
    return _payload(row)


def generate_due(
    db: Session,
    day: date | None = None,
    limit: int | None = None,
    check_switch: bool = True,
    model_name: str | None = None,
) -> dict:
    """为所有启用账号补齐当天的建议；跳过已 ready、失败达上限与生成中的行。"""
    day = day or today_local()
    if check_switch and not settings.advice_auto_enabled:
        return {"day": day.isoformat(), "scanned": 0, "generated": 0, "skipped": 0,
                "failed": 0, "items": []}

    users = db.query(User).filter(User.status == "启用").all()
    if limit:
        users = users[:limit]

    result = {"day": day.isoformat(), "scanned": len(users), "generated": 0, "skipped": 0,
              "failed": 0, "items": []}
    for user in users:
        row = _get_row(db, user.id, day)
        if row and row.status == STATUS_READY:
            result["skipped"] += 1
            continue
        if row and row.status == STATUS_FAILED and (row.attempts or 0) >= settings.advice_max_attempts:
            result["skipped"] += 1
            continue
        if row and row.status == STATUS_GENERATING and not _is_stale_generating(row):
            result["skipped"] += 1
            continue
        try:
            payload = generate(db, user, day, model_name=model_name)
            result["generated"] += 1
            result["items"].append(
                {"user_id": user.id, "status": payload["status"], "verdict": payload["verdict"]}
            )
        except Exception as exc:  # 单个用户失败不阻断其余用户
            db.rollback()
            result["failed"] += 1
            result["items"].append({"user_id": user.id, "status": "failed", "error": str(exc)[:120]})
            logger.warning("daily advice due failed: user=%s day=%s err=%s", user.id, day, exc)
    return result


def get_for_sidebar(user_id: int, day: date | None = None) -> dict:
    """侧栏轻量读取：一条索引查询，不调模型、不下发 facts。"""
    from database import SessionLocal

    db = SessionLocal()
    try:
        return read(db, user_id, day)
    finally:
        db.close()
