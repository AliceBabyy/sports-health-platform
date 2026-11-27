"""平台技能种子（幂等）：减重分析、游泳复盘、10 个健康档案专项、定制健身计划。

首次插入使用代码注册的元数据；已存在的代码技能只同步 ``kind`` 与代码版本，
名称/描述/分类/斜杠别名/状态以数据库为准，不覆盖管理员在 /system/skills 的调整。
提示词技能的 prompt 定义由文件加载，内容变化时新增版本。

用法：
    python scripts/seed_agent_skills.py
"""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.prompts.loader import load_system_prompt
from app.modules.agent.models import AgentSkill, AgentSkillVersion
from app.modules.agent.skills.definition import parse_prompt_definition
from app.modules.agent.skills.platform import CODE_SKILLS
from app.modules.agent.skills.prompt_skills import PLATFORM_PROMPT_SKILLS
from database import SessionLocal


def _definition_hash(definition: dict) -> str:
    payload = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _seed_prompt_skills(db) -> None:
    for key, meta in PLATFORM_PROMPT_SKILLS.items():
        definition = {
            "schema_version": 1,
            "prompt": load_system_prompt(meta.prompt_id),
        }
        parse_prompt_definition(definition)
        new_hash = _definition_hash(definition)
        skill = (
            db.query(AgentSkill)
            .filter(AgentSkill.scope == "system", AgentSkill.skill_key == key)
            .first()
        )
        if skill is None:
            skill = AgentSkill(
                scope="system", owner_user_id=None, skill_key=key, name=meta.name,
                description=meta.description, kind="prompt", category=meta.category,
                status="active", slash_alias=meta.slash_alias, current_version_no=None,
            )
            db.add(skill)
            db.flush()
        elif skill.kind != "prompt":
            raise RuntimeError(f"平台提示词技能键 {key} 已被其他类型占用")

        latest = (
            db.query(AgentSkillVersion)
            .filter(AgentSkillVersion.skill_id == skill.id)
            .order_by(AgentSkillVersion.version_no.desc())
            .first()
        )
        if latest is not None and latest.definition_hash == new_hash:
            latest.definition = definition
            latest.published_at = latest.published_at or datetime.now()
            skill.current_version_no = latest.version_no
        else:
            next_no = (latest.version_no + 1) if latest else 1
            version = AgentSkillVersion(
                skill_id=skill.id, version_no=next_no, definition=definition,
                definition_hash=new_hash, created_by=None, published_at=datetime.now(),
            )
            db.add(version)
            skill.current_version_no = next_no
        db.commit()
        print(f"已就绪：{skill.name}（{key}）")


def seed(db) -> None:
    for key, code in CODE_SKILLS.items():
        skill = (
            db.query(AgentSkill)
            .filter(AgentSkill.scope == "system", AgentSkill.skill_key == key)
            .first()
        )
        if skill is None:
            skill = AgentSkill(
                scope="system", owner_user_id=None, skill_key=key, name=code.name,
                description=code.description, kind="code", category=code.category,
                status="active", current_version_no=code.version,
                slash_alias=code.slash_alias,
            )
            db.add(skill)
            db.flush()
        else:
            # 代码技能的定义仍随代码版本更新；名称、描述、分类、别名与状态
            # 已可在 /system/skills 维护，种子不再覆盖，避免管理员改动被重置。
            skill.kind = "code"
            skill.current_version_no = code.version
            if skill.status in ("draft", "archived", None):
                skill.status = "active"

        version = (
            db.query(AgentSkillVersion)
            .filter(AgentSkillVersion.skill_id == skill.id,
                    AgentSkillVersion.version_no == code.version)
            .first()
        )
        if version is None:
            version = AgentSkillVersion(
                skill_id=skill.id, version_no=code.version,
                definition={"kind": "code", "code_key": key},
                definition_hash="", created_by=None, published_at=datetime.now(),
            )
            db.add(version)
        else:
            version.definition = {"kind": "code", "code_key": key}
            version.published_at = version.published_at or datetime.now()
        db.commit()
        print(f"已就绪：{skill.name}（{key}）")

    _seed_prompt_skills(db)


def main() -> None:
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
