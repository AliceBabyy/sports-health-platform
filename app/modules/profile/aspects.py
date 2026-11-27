"""健康档案的固定 aspect 模板。

aspect 只约束“这条答案属于哪个方面”，不决定专项 skill、题目数量或出题规则；
专项 skill 及其允许 aspect 见 app/modules/profile/aspect_skills.py。
"""
from __future__ import annotations

ASPECTS: tuple[dict, ...] = (
    {"key": "goal", "label": "目标", "description": "减重、降体脂、增肌、增重、塑形等目标与节奏"},
    {"key": "diet", "label": "饮食", "description": "三餐、口味、忌口、外卖、补剂与饮食执行条件"},
    {"key": "exercise", "label": "运动基础", "description": "运动经历、能力、偏好与不喜欢的运动"},
    {"key": "training", "label": "训练安排", "description": "频率、时长、时段、强度与训练结构"},
    {"key": "environment", "label": "运动条件", "description": "场地、器械、通勤与可用的运动环境"},
    {"key": "preference", "label": "运动偏好", "description": "喜欢的项目、课程、搭子与坚持方式"},
    {"key": "sleep", "label": "睡眠", "description": "入睡、时长、质量、作息规律与白天精力"},
    {"key": "lifestyle", "label": "生活方式", "description": "上下班时间、单双休、工作类型与日常活动量"},
    {"key": "psych", "label": "心理状态", "description": "压力、情绪、动力与对运动/饮食的心理感受"},
    {"key": "medical", "label": "伤病与限制", "description": "旧伤、疼痛、疾病、医生限制与康复情况"},
    {"key": "cycle", "label": "生理期", "description": "周期规律、经期感受、经期运动与不适"},
    {"key": "posture", "label": "形体矫正", "description": "驼背、骨盆前倾、腿型、肋骨外翻与下肢循环等体态问题"},
    {"key": "other", "label": "补充", "description": "不属于以上方面、但会影响运动与健康管理的补充信息"},
)

ASPECT_KEYS: tuple[str, ...] = tuple(item["key"] for item in ASPECTS)
ASPECT_LABELS: dict[str, str] = {item["key"]: item["label"] for item in ASPECTS}


def aspect_label(key: str) -> str:
    return ASPECT_LABELS.get(key, key)
