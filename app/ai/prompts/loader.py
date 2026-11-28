"""Load prompts by fixed ID without accepting arbitrary filesystem paths."""
from importlib.resources import files
from string import Formatter

from langchain_core.prompts import ChatPromptTemplate

# 值可以是文件名，也可以是 (文件名, section)。section 形式用于把同一份文件里的
# 多段专项提示词注册成多个固定 ID，调用方仍然只能按 ID 加载。
PROMPTS = {
    "foundation_probe.v1": "foundation_probe_v1.txt",
    "sport_import_training.v1": "sport_import_training_v1.txt",
    "sport_import_swim.v1": "sport_import_swim_v1.txt",
    "sport_import_dance.v1": "sport_import_dance_v1.txt",
    "agent_chat.v9": "agent_chat_v9.txt",
    "persona_nutrition.v1": "persona_nutrition_v1.txt",
    "persona_e_trainer.v3": "persona_e_trainer_v3.txt",
    "persona_training_coach.v2": "persona_training_coach_v2.txt",
    "persona_health_profile_test.v3": "persona_health_profile_test_v3.txt",
    "persona_health_profile_test_guard.v3": "persona_health_profile_test_guard_v3.txt",
    "profile_aspect_goal.v1": ("profile_aspect_skills_v1.txt", "goal"),
    "profile_aspect_diet.v1": ("profile_aspect_skills_v1.txt", "diet"),
    "profile_aspect_exercise.v1": ("profile_aspect_skills_v1.txt", "exercise"),
    "profile_aspect_fitness.v1": ("profile_aspect_skills_v1.txt", "fitness"),
    "profile_aspect_sleep.v1": ("profile_aspect_skills_v1.txt", "sleep"),
    "profile_aspect_lifestyle.v1": ("profile_aspect_skills_v1.txt", "lifestyle"),
    "profile_aspect_cycle.v1": ("profile_aspect_skills_v1.txt", "cycle"),
    "profile_aspect_posture.v1": ("profile_aspect_skills_v1.txt", "posture"),
    "profile_aspect_medical.v1": ("profile_aspect_skills_v1.txt", "medical"),
    "profile_aspect_extra.v1": ("profile_aspect_skills_v1.txt", "extra"),
    "skill_arg_parse.v1": "skill_arg_parse_v1.txt",
    "weekly_report.v1": "weekly_report_v1.txt",
    "monthly_report.v1": "monthly_report_v1.txt",
    "daily_advice.v4": "daily_advice_v4.txt",
    "skill_custom_fitness_plan.v1": "skill_custom_fitness_plan_v1.txt",
}


def registered_prompt_files() -> set[str]:
    """PROMPTS 引用到的全部 .txt 文件；同一文件可被多个 section ID 共用。"""
    result: set[str] = set()
    for value in PROMPTS.values():
        result.add(value[0] if isinstance(value, tuple) else value)
    return result


def _read(filename: str) -> str:
    return files("app.ai.prompts").joinpath(filename).read_text(encoding="utf-8")


def _extract_section(source: str, section: str) -> str:
    marker = f"===== {section} ====="
    lines = source.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == marker:
            start = index
            break
    if start is None:
        raise ValueError(f"提示词 section 不存在：{section}")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].strip().startswith("===== ") and lines[index].strip().endswith(" ====="):
            end = index
            break
    content = "\n".join(lines[start + 1:end]).strip()
    if not content:
        raise ValueError(f"提示词 section 为空：{section}")
    return content


def _load_source(prompt_id: str, **variables: str) -> str:
    entry = PROMPTS.get(prompt_id)
    if entry is None:
        raise ValueError("未知提示词版本")
    if isinstance(entry, tuple):
        filename, section = entry
        source = _extract_section(_read(filename), section)
    else:
        source = _read(entry)
    expected = {name for _, name, _, _ in Formatter().parse(source) if name}
    if expected != set(variables):
        raise ValueError("提示词变量不匹配")
    return source.format(**variables)


def load_prompt(prompt_id: str, **variables: str) -> ChatPromptTemplate:
    source = _load_source(prompt_id, **variables)
    return ChatPromptTemplate.from_messages([
        ("system", source),
        ("human", "{input_text}"),
    ])


def load_system_prompt(prompt_id: str, **variables: str) -> str:
    """Return rendered system text only (for LangGraph nodes)."""
    return _load_source(prompt_id, **variables)
