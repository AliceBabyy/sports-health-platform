"""健康/运动档案题目定义：题目 key 的唯一来源。

answers 以 `key -> 用户文本` 存进 health_profile.answers（JSON）。key 是稳定标识，
前端渲染、后端校验与 AI 读取都以本文件为准：改文案可以，改 key 会让旧答案失去归属。
本版全部题目都是开放式文本，不做枚举与选项校验，只限制长度。
"""

# 至少回答几项才记 completed_at（用于判断「是否填过」），
# 不阻断保存——只写一两句也能先存下来。
COMPLETION_MIN_ANSWERS = 3

QUESTIONS = [
    {
        "key": "goal",
        "group": "目标与节奏",
        "label": "你的主要目标",
        "hint": "减脂、降体脂、增肌、增重、塑形、提升体能，或者别的",
        "placeholder": "想变成什么样，或者想达成什么",
        "max_length": 200,
    },
    {
        "key": "horizon",
        "group": "目标与节奏",
        "label": "想达成的程度或期限",
        "hint": "没有明确期限可以写「不设期限」",
        "placeholder": "如三个月减 5 公斤，或先坚持一个月",
        "max_length": 120,
    },
    {
        "key": "weekly",
        "group": "目标与节奏",
        "label": "一周大概能练几次",
        "hint": "写数字或「不固定」，这是你的预期，不是实际记录",
        "placeholder": "如 3 次，周末为主",
        "max_length": 80,
    },
    {
        "key": "session",
        "group": "目标与节奏",
        "label": "单次能练多久",
        "hint": "按平常真正能留出的时间写",
        "placeholder": "如 60 分钟，午休只有 30 分钟",
        "max_length": 80,
    },
    {
        "key": "sports",
        "group": "训练方式与条件",
        "label": "常做的运动和运动方式",
        "hint": "健身、游泳、舞蹈、跑步、骑行、球类、居家自重都可以写",
        "placeholder": "如每周两次健身房、一次游泳",
        "max_length": 200,
    },
    {
        "key": "place",
        "group": "训练方式与条件",
        "label": "场地和器材",
        "hint": "健身房、家里、户外、泳池，以及能用的器械",
        "placeholder": "如公司健身房有哑铃和跑步机，家里只有弹力带",
        "max_length": 200,
    },
    {
        "key": "experience",
        "group": "训练方式与条件",
        "label": "训练经验和强度偏好",
        "hint": "练了多久、熟不熟动作、喜欢轻松还是上强度",
        "placeholder": "如练了一年，动作基本会，但不喜欢练到力竭",
        "max_length": 150,
    },
    {
        "key": "habits",
        "group": "习惯与限制",
        "label": "运动习惯、癖好与偏好",
        "hint": "喜欢什么、讨厌什么、什么时间最练得动",
        "placeholder": "如不喜欢跑步，讨厌人多，习惯晚上练",
        "max_length": 255,
    },
    {
        "key": "limits",
        "group": "习惯与限制",
        "label": "伤病或身体限制",
        "hint": "写清部位和要避开的动作，没有可以写「无」",
        "placeholder": "如右膝旧伤，避免深蹲和跳跃",
        "max_length": 255,
    },
    {
        "key": "note",
        "group": "习惯与限制",
        "label": "其它想让我知道的",
        "hint": "饮食、作息、目标变化，任何影响训练安排的事",
        "placeholder": "如经常出差，出差周只能做自重训练",
        "max_length": 255,
    },
]

QUESTION_KEYS = frozenset(q["key"] for q in QUESTIONS)
QUESTION_MAP = {q["key"]: q for q in QUESTIONS}


def grouped_questions() -> list[dict]:
    """按定义顺序分组，供页面渲染（同组题目连续出现）。"""
    groups: list[dict] = []
    by_name: dict[str, dict] = {}
    for question in QUESTIONS:
        group = by_name.get(question["group"])
        if group is None:
            group = {"name": question["group"], "items": []}
            by_name[question["group"]] = group
            groups.append(group)
        group["items"].append(question)
    return groups
