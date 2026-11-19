"""健康档案方面（aspect）固定模板。

档案按“一个方面一条记录”管理，方面的 key 只能来自本文件；
模型可以决定某个方面下具体问什么，但不能自行新增方面。
新增方面需要同步数据库 CHECK、迁移脚本、提示词和测试。
"""

ASPECTS = (
    {"key": "goal", "label": "目标与动机", "description": "目标、期限、优先级和坚持动机"},
    {"key": "diet", "label": "饮食营养", "description": "饮食结构、忌口、进食节奏、补剂与酒精"},
    {"key": "exercise", "label": "日常运动", "description": "日常活动量、运动偏好和可执行的运动方式"},
    {"key": "training", "label": "训练安排", "description": "训练频率、时长、经验、强度和恢复"},
    {"key": "sleep", "label": "睡眠作息", "description": "睡眠时长、质量、入睡与白天疲劳"},
    {"key": "lifestyle", "label": "生活习惯", "description": "工作节奏、久坐、出差、家庭与环境限制"},
    {"key": "medical", "label": "身体伤病", "description": "伤病、疾病、用药、过敏和手术"},
    {"key": "cycle", "label": "生理周期", "description": "周期规律、经期症状和周期对运动的影响"},
    {"key": "psych", "label": "压力情绪", "description": "压力、情绪、身体意象和动力变化"},
    {"key": "environment", "label": "环境条件", "description": "场地、器材、天气和可替代条件"},
    {"key": "preference", "label": "执行偏好", "description": "喜欢/讨厌、反馈方式、时间和执行偏好"},
    {"key": "other", "label": "其他", "description": "不属于以上方面的补充信息"},
)

ASPECT_MAP = {item["key"]: item for item in ASPECTS}
ASPECT_KEYS = frozenset(ASPECT_MAP)
ASPECT_LABELS = {item["key"]: item["label"] for item in ASPECTS}

# 固定问卷 key → aspect；新增固定题时在这里补映射。
FIXED_QUESTION_ASPECTS = {
    "goal": "goal",
    "horizon": "goal",
    "weekly": "training",
    "session": "training",
    "sports": "exercise",
    "place": "environment",
    "experience": "training",
    "habits": "preference",
    "limits": "medical",
    "note": "other",
}


def aspect_for_question(key: str) -> str:
    """取固定题所属方面；未知 key 归入 other，避免迁移时丢数据。"""
    return FIXED_QUESTION_ASPECTS.get(key, "other")


def aspect_label(key: str) -> str:
    return ASPECT_LABELS.get(key, ASPECT_LABELS["other"])
