"""把四个临时健身专项合并为一个 profile_fitness，保留角色授权并清理旧技能。

用法：
    python scripts/seed_agent_skills.py
    python scripts/migrate_profile_fitness_merge.py
    python scripts/seed_agent_personas.py

脚本只删除 `profile_fitness_base/goal/plan/env` 四条临时技能及其版本/运行记录；
不会删除 `health_profile` 里的用户答案。旧技能没有运行记录时可直接清理。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.agent.models import AgentPersona, AgentSkill
from app.modules.auth.models import User  # noqa: F401  # 让 SQLAlchemy 能解析 users 外键
from database import SessionLocal

OLD_KEYS = (
    "profile_fitness_base",
    "profile_fitness_goal",
    "profile_fitness_plan",
    "profile_fitness_env",
)
NEW_KEY = "profile_fitness"


def main() -> None:
    with SessionLocal() as db:
        old_skills = db.query(AgentSkill).filter(AgentSkill.skill_key.in_(OLD_KEYS)).all()
        if old_skills:
            for skill in old_skills:
                db.delete(skill)
            print(f"删除旧健身专项：{', '.join(OLD_KEYS)}")
        else:
            print("没有需要删除的旧健身专项")

        for persona in db.query(AgentPersona).all():
            grants = persona.skill_grants
            if grants is None:
                continue
            old_grants = set(grants) & set(OLD_KEYS)
            if not old_grants:
                continue
            next_grants = [key for key in grants if key not in OLD_KEYS]
            if NEW_KEY not in next_grants:
                next_grants.append(NEW_KEY)
            persona.skill_grants = next_grants
        db.commit()
    print("旧技能已清理；请再运行 scripts/seed_agent_personas.py 刷新角色授权")


if __name__ == "__main__":
    main()
