"""平台技能种子（幂等）：减重分析、游泳复盘、9 个健康档案专项。

用法：
    python scripts/seed_agent_skills.py
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.agent.models import AgentSkill, AgentSkillVersion
from app.modules.agent.skills.platform import CODE_SKILLS
from database import SessionLocal


def main() -> None:
    db = SessionLocal()
    try:
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
                skill.name = code.name
                skill.description = code.description
                skill.kind = "code"
                skill.category = code.category
                skill.current_version_no = code.version
                skill.slash_alias = code.slash_alias
                # 管理员在 /system/skills 停用的代码技能不因种子脚本被强行重新启用
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
            print(f"已就绪：{code.name}（{key}）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
