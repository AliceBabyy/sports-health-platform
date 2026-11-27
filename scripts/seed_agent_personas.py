"""平台内置角色种子（幂等）：营养师、电子私教、健康档案测试。

用法：
    python scripts/seed_agent_personas.py
"""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.prompts.loader import load_system_prompt
from app.modules.agent.models import AgentPersona, AgentPersonaVersion
from app.modules.agent.personas.definition import validate_definition
from app.modules.profile.aspect_skills import PROFILE_SKILL_KEYS
import models_registry  # noqa: F401  确保 users 等关联表注册到 Base
from database import SessionLocal

PROFILE_TEST_READ_TOOLS = [
    "ask_user",
    "get_profile_info",
    "get_body_measurements",
    "get_workout_summary",
    "get_fitness_records",
    "get_swim_records",
    "get_dance_records",
    "get_state_records",
    "get_cycle_records",
    "save_health_profile_aspect",
]

PLATFORM_PERSONAS = [
    {
        "key": "nutrition",
        "name": "营养师",
        "description": "围绕饮食结构、热量与体重变化给建议",
        "prompt_id": "persona_nutrition.v1",
        "sort_order": 1,
    },
    {
        "key": "e_trainer",
        "name": "电子私教",
        "description": "围绕训练计划、动作质量与恢复给建议",
        "prompt_id": "persona_e_trainer.v1",
        "sort_order": 2,
    },
    {
        "key": "health_profile_test",
        "name": "健康档案测试",
        "description": "按专项逐项建立健康档案，回答后写入档案",
        "prompt_id": "persona_health_profile_test.v3",
        "sort_order": 3,
        "tool_grants": PROFILE_TEST_READ_TOOLS,
        "skill_grants": sorted(PROFILE_SKILL_KEYS),
    },
]


def _hash(definition: dict) -> str:
    payload = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    db = SessionLocal()
    try:
        for item in PLATFORM_PERSONAS:
            definition = {"schema_version": 1, "prompt": load_system_prompt(item["prompt_id"])}
            errors, _ = validate_definition(definition)
            if errors:
                raise RuntimeError(
                    f"内置角色提示词不合法（{item['key']} / {item['prompt_id']}）：{errors}"
                )
            new_hash = _hash(definition)
            persona = (
                db.query(AgentPersona)
                .filter(AgentPersona.scope == "system", AgentPersona.persona_key == item["key"])
                .first()
            )
            if persona is None:
                persona = AgentPersona(
                    scope="system", owner_user_id=None, persona_key=item["key"],
                    name=item["name"], description=item["description"],
                    status="active", sort_order=item["sort_order"], current_version_no=None,
                )
                db.add(persona)
                db.flush()
            else:
                persona.name = item["name"]
                persona.description = item["description"]
                persona.status = "active"
                persona.sort_order = item["sort_order"]

            if "tool_grants" in item:
                persona.tool_grants = item["tool_grants"]
            if "skill_grants" in item:
                persona.skill_grants = item["skill_grants"]

            latest = db.query(AgentPersonaVersion).filter(
                AgentPersonaVersion.persona_id == persona.id
            ).order_by(AgentPersonaVersion.version_no.desc()).first()
            if latest is not None and latest.definition_hash == new_hash:
                latest.definition = definition
                latest.published_at = latest.published_at or datetime.now()
                persona.current_version_no = latest.version_no
            else:
                next_no = (latest.version_no + 1) if latest else 1
                version = AgentPersonaVersion(
                    persona_id=persona.id, version_no=next_no, definition=definition,
                    definition_hash=new_hash, created_by=None, published_at=datetime.now(),
                )
                db.add(version)
                persona.current_version_no = next_no
            db.commit()
            print(f"已就绪：{item['name']}（{item['key']}，v{persona.current_version_no}）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
