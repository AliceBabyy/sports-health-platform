"""健康档案专项 skill 的固定元数据。

十个专项 skill 一一对应一套专项档案；每套由 AI 在提示词约束下现场生成 3~10 题（健身档案 6~10 题），
题目不写死在代码或数据库里。这里只固定：
- skill key / 名称 / 斜杠命令；
- 该专项允许出现的 aspect（保存时强制校验）；
- 提示词 ID 与提示词文件中的 section。
"""
from __future__ import annotations

ASPECT_SKILLS: tuple[dict, ...] = (
    {
        "key": "profile_goal",
        "name": "测试-目标档案",
        "slash_alias": "目标档案",
        "description": "梳理减重、降体脂、增肌、增重、塑形等目标与节奏，生成一套目标专项问题。",
        "aspects": ("goal",),
        "prompt_id": "profile_aspect_goal.v1",
        "prompt_section": "goal",
        "female_only": False,
        "sort_order": 10,
    },
    {
        "key": "profile_diet",
        "name": "测试-饮食档案",
        "slash_alias": "饮食档案",
        "description": "了解三餐、口味、忌口、外卖、补剂与执行条件，生成一套饮食专项问题。",
        "aspects": ("diet",),
        "prompt_id": "profile_aspect_diet.v1",
        "prompt_section": "diet",
        "female_only": False,
        "sort_order": 20,
    },
    {
        "key": "profile_exercise",
        "name": "测试-运动档案",
        "slash_alias": "运动档案",
        "description": "了解运动经历、项目类型、能力、场地器械、频率时段与偏好，生成一套运动专项问题。",
        "aspects": ("exercise", "sport", "training", "environment", "preference"),
        "prompt_id": "profile_aspect_exercise.v1",
        "prompt_section": "exercise",
        "female_only": False,
        "sort_order": 30,
    },
    {
        "key": "profile_fitness",
        "name": "测试-健身档案",
        "slash_alias": "健身档案",
        "description": "了解健身目标、基础、项目类型、频率分化、器械条件与偏好，一次生成一套较完整的健身专项问题。",
        "aspects": ("exercise", "sport", "goal", "training", "environment", "preference"),
        "prompt_id": "profile_aspect_fitness.v1",
        "prompt_section": "fitness",
        "female_only": False,
        "sort_order": 31,
    },
    {
        "key": "profile_sleep",
        "name": "测试-睡眠档案",
        "slash_alias": "睡眠档案",
        "description": "了解入睡、时长、质量、作息规律与白天精力，生成一套睡眠专项问题。",
        "aspects": ("sleep",),
        "prompt_id": "profile_aspect_sleep.v1",
        "prompt_section": "sleep",
        "female_only": False,
        "sort_order": 40,
    },
    {
        "key": "profile_lifestyle",
        "name": "测试-生活方式",
        "slash_alias": "生活方式",
        "description": "了解上下班时间、单双休、工作类型、日常活动量与压力情绪，生成一套生活方式专项问题。",
        "aspects": ("lifestyle", "psych"),
        "prompt_id": "profile_aspect_lifestyle.v1",
        "prompt_section": "lifestyle",
        "female_only": False,
        "sort_order": 50,
    },
    {
        "key": "profile_cycle",
        "name": "测试-生理期档案",
        "slash_alias": "生理期档案",
        "description": "了解周期规律、经期感受、经期运动与不适，生成一套生理期专项问题（仅女性）。",
        "aspects": ("cycle",),
        "prompt_id": "profile_aspect_cycle.v1",
        "prompt_section": "cycle",
        "female_only": True,
        "sort_order": 60,
    },
    {
        "key": "profile_posture",
        "name": "测试-形体矫正",
        "slash_alias": "形体矫正",
        "description": "了解驼背、骨盆前倾、腿型、肋骨外翻与下肢循环等体态问题，生成一套形体专项问题。",
        "aspects": ("posture",),
        "prompt_id": "profile_aspect_posture.v1",
        "prompt_section": "posture",
        "female_only": False,
        "sort_order": 70,
    },
    {
        "key": "profile_medical",
        "name": "测试-伤病档案",
        "slash_alias": "伤病档案",
        "description": "了解旧伤、疼痛、疾病、医生限制与康复情况，生成一套伤病专项问题。",
        "aspects": ("medical",),
        "prompt_id": "profile_aspect_medical.v1",
        "prompt_section": "medical",
        "female_only": False,
        "sort_order": 80,
    },
    {
        "key": "profile_extra",
        "name": "测试-档案补充",
        "slash_alias": "档案补充",
        "description": "收集不属于以上专项、但会影响运动与健康管理的补充信息，生成一套补充问题。",
        "aspects": ("other",),
        "prompt_id": "profile_aspect_extra.v1",
        "prompt_section": "extra",
        "female_only": False,
        "sort_order": 90,
    },
)

PROFILE_SKILL_KEYS: frozenset[str] = frozenset(item["key"] for item in ASPECT_SKILLS)
PROFILE_SKILL_MAP: dict[str, dict] = {item["key"]: item for item in ASPECT_SKILLS}
PROFILE_ASPECTS_BY_SKILL: dict[str, frozenset[str]] = {
    item["key"]: frozenset(item["aspects"]) for item in ASPECT_SKILLS
}


def skill_name(skill_key: str) -> str:
    item = PROFILE_SKILL_MAP.get(skill_key)
    return item["name"] if item else skill_key


def skill_aspects(skill_key: str) -> frozenset[str]:
    return PROFILE_ASPECTS_BY_SKILL.get(skill_key, frozenset())


def skill_slash(skill_key: str) -> str:
    item = PROFILE_SKILL_MAP.get(skill_key)
    return f"/{item['slash_alias']}" if item else skill_key


def skill_female_only(skill_key: str) -> bool:
    """专项是否仅女性可用（目前只有 profile_cycle）。"""
    item = PROFILE_SKILL_MAP.get(skill_key)
    return bool(item and item.get("female_only"))
