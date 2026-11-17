"""把技能包装成 LangChain 工具：模型按需选择，或由服务端注入斜杠调用。"""
from __future__ import annotations

from datetime import date

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool

from app.core.exceptions import AppError
from app.modules.agent.models import AgentSkill, AgentSkillVersion
from app.modules.agent.skills.argument import validate_args
from app.modules.agent.skills.execution import execute_skill
from app.modules.agent.skills.management import resolved_from_version
from app.modules.agent.skills.registry import ResolvedSkill, build_args_model, describe_skill
from database import SessionLocal


def _user_id(config: RunnableConfig | None) -> int:
    uid = (config or {}).get("configurable", {}).get("user_id")
    if not uid:
        raise AppError(400, "缺少用户身份，无法执行技能")
    return uid


def build_skill_tool(skill: ResolvedSkill) -> StructuredTool:
    schema = build_args_model(skill)
    skill_id = skill.id
    version_no = skill.version_no

    async def _run(config: RunnableConfig = None, **kwargs):
        uid = _user_id(config)
        with SessionLocal() as db:
            row = db.get(AgentSkill, skill_id)
            if row is None or row.status != "active" or row.current_version_no != version_no:
                return {"ok": False, "status": "disabled", "summary": "该技能已停用或版本已变更，请重新发送命令。"}
            if row.scope == "user" and row.owner_user_id != uid:
                return {"ok": False, "status": "forbidden", "summary": "无权调用该技能。"}
            version = db.query(AgentSkillVersion).filter(
                AgentSkillVersion.skill_id == skill_id,
                AgentSkillVersion.version_no == version_no,
            ).first()
            if version is None:
                return {"ok": False, "status": "not_found", "summary": "技能版本不存在。"}
            resolved = resolved_from_version(row, version)
            args, errors, warnings, missing = validate_args(resolved, kwargs, date.today())
            if errors or missing:
                return {"ok": False, "status": "invalid_args", "errors": errors,
                        "missing": missing, "summary": "技能参数不完整或无效。"}
            configurable = (config or {}).get("configurable", {})
            parse_meta = configurable.get("skill_parse") or {"strategy": "tool_args", "warnings": warnings}
            parse_meta = {**parse_meta, "warnings": [*parse_meta.get("warnings", []), *warnings]}
            result = execute_skill(
                db, uid, resolved, args,
                trigger=configurable.get("skill_trigger", "model"),
                conversation_id=configurable.get("conversation_id"),
                parse_meta=parse_meta,
            )
            db.commit()
            return result

    return StructuredTool.from_function(
        coroutine=_run,
        name=skill.tool_name,
        description=describe_skill(skill),
        args_schema=schema,
    )
