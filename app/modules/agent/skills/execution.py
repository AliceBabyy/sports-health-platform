"""技能执行与审计：统一代码技能与声明式技能的结果契约。"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.agent.models import AgentSkillRun
from app.modules.agent.skills.definition import parse_definition, prompt_text
from app.modules.agent.skills.engine import execute_declarative
from app.modules.agent.skills.platform import CODE_SKILLS
from app.modules.agent.skills.registry import ResolvedSkill

logger = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def execute_skill(
    db: Session,
    user_id: int,
    skill: ResolvedSkill,
    args: dict,
    *,
    trigger: str = "model",
    conversation_id: int | None = None,
    parse_meta: dict | None = None,
) -> dict:
    started = time.perf_counter()
    parse_meta = parse_meta or {"strategy": "direct"}
    status = "ok"
    error_code = None
    error_message = None
    data: dict = {}
    try:
        if skill.kind == "code":
            code = CODE_SKILLS[skill.key]
            instance = code.input_model(**args)
            data = code.run(db, user_id, instance)
        elif skill.kind == "prompt":
            instructions = prompt_text(skill.kind, skill.definition)
            if not instructions:
                raise ValueError("提示词技能定义缺失")
            # 提示词技能不取数：把提示词作为指令交给模型，由模型完成回答
            data = {
                "status": "ok",
                "range": None,
                "sample_size": 0,
                "outputs": [],
                "facts": {"prompt_chars": len(instructions)},
                "summary": instructions,
                "caveats": [],
            }
        else:
            defn = parse_definition(skill.definition)
            data = execute_declarative(db, user_id, defn, args)
    except Exception:  # 工具/技能失败不能拖垮整轮对话
        logger.exception("skill execution failed: skill=%s user=%s", skill.key, user_id)
        status = "failed"
        error_code = "SKILL_EXECUTION_FAILED"
        error_message = "技能执行失败"
        data = {
            "status": "failed",
            "range": {"start": None, "end": None},
            "sample_size": 0,
            "outputs": [],
            "facts": {},
            "summary": "技能执行失败，未生成有效结果。",
            "caveats": ["技能执行失败，请稍后重试。"],
        }

    status = data.get("status", status)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    meta = {
        "model": parse_meta.get("model"),
        "prompt_version": parse_meta.get("prompt_version"),
        "strategy": parse_meta.get("strategy", "direct"),
        "parse_elapsed_ms": parse_meta.get("elapsed_ms", 0),
        "elapsed_ms": elapsed_ms,
        "warnings": parse_meta.get("warnings", []),
    }
    result = {
        "ok": status == "ok",
        "status": status,
        "skill": skill.key,
        "name": skill.name,
        "version": f"v{skill.version_no}",
        "scope": skill.scope,
        "kind": skill.kind,
        "range": data.get("range"),
        "sample_size": data.get("sample_size", 0),
        "outputs": data.get("outputs", []),
        "facts": data.get("facts", {}),
        "summary": data.get("summary", ""),
        "caveats": data.get("caveats", []),
        "meta": meta,
    }

    run = AgentSkillRun(
        skill_id=skill.id, version_no=skill.version_no, user_id=user_id,
        conversation_id=conversation_id, trigger=trigger, status=status,
        error_code=error_code, error_message=error_message,
        args=_json_safe(args), parse=_json_safe(meta),
        sample_size=result["sample_size"], duration_ms=elapsed_ms,
    )
    db.add(run)
    db.flush()
    return result


def test_skill(db: Session, user_id: int, skill: ResolvedSkill, args: dict) -> dict:
    return execute_skill(db, user_id, skill, args, trigger="test", conversation_id=None,
                         parse_meta={"strategy": "test"})
