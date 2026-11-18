"""全局常量与枚举：指标 key、泳姿、训练状态机、周期七阶段、运动四档、疼痛等级、趋势档位。

魔法值（窗口天数、周期默认值、阶段边界）集中在这里，改动只动常量、不动接口。
"""
from datetime import date, timedelta

# ---------- 身材字段（4 表拆分，BD 重构） ----------
# 每种维度直接定义为字段；元组：(标签, 单位, 数据库列名, 所属分组)。
# 分组 → 表：basic→body_basic_records、goal→body_basic_goal、
#          girth→body_dimensions_records、target→body_dimensions_goal
BODY_FIELDS: dict[str, tuple[str, str, str, str]] = {
    "height":         ("身高",     "cm", "height_cm",           "basic"),
    "weight":         ("体重",     "kg", "weight_kg",           "basic"),
    "body_fat":       ("体脂率",   "%",  "body_fat_pct",        "basic"),
    "target_weight":  ("目标体重", "kg", "target_weight_kg",    "goal"),
    "target_body_fat":("目标体脂率", "%", "target_body_fat_pct", "goal"),
    "neck":           ("颈围",     "cm", "neck_cm",             "girth"),
    "shoulder_width": ("肩宽",     "cm", "shoulder_width_cm",   "girth"),
    "arm":            ("臂围",     "cm", "arm_circ_cm",         "girth"),
    "chest":          ("胸围",     "cm", "chest_circ_cm",       "girth"),
    "waist":          ("腰围",     "cm", "waist_circ_cm",       "girth"),
    "hip":            ("臀围",     "cm", "hip_circ_cm",         "girth"),
    "thigh":          ("大腿围",   "cm", "thigh_circ_cm",       "girth"),
    "calf":           ("小腿围",   "cm", "calf_circ_cm",        "girth"),
    "target_arm":     ("目标臂围", "cm", "target_arm_circ_cm",  "target"),
    "target_chest":   ("目标胸围", "cm", "target_chest_circ_cm","target"),
    "target_waist":   ("目标腰围", "cm", "target_waist_circ_cm","target"),
    "target_hip":     ("目标臀围", "cm", "target_hip_circ_cm",  "target"),
    "target_thigh":   ("目标大腿围", "cm", "target_thigh_circ_cm", "target"),
    "target_calf":    ("目标小腿围", "cm", "target_calf_circ_cm", "target"),
}
BODY_KEYS = list(BODY_FIELDS.keys())
BODY_LABELS = {k: v[0] for k, v in BODY_FIELDS.items()}
BODY_UNITS = {k: v[1] for k, v in BODY_FIELDS.items()}
BODY_COLUMNS = {k: v[2] for k, v in BODY_FIELDS.items()}
# 分组 → key 列表（与 4 张表一一对应）
BODY_GROUPS: dict[str, list[str]] = {
    "basic":  ["height", "weight", "body_fat"],
    "goal":   ["target_weight", "target_body_fat"],
    "girth":  ["neck", "shoulder_width", "arm", "chest", "waist", "hip", "thigh", "calf"],
    "target": ["target_arm", "target_chest", "target_waist", "target_hip", "target_thigh", "target_calf"],
}
GROUP_LABELS = {
    "basic": "身体基础",
    "goal": "期望指标",
    "girth": "围度",
    "target": "目标围度",
}
# 兼容别名：smoke_test / 旧调用（key → 列名不变）
METRIC_KEYS = BODY_KEYS
METRIC_LABELS = BODY_LABELS
METRIC_UNITS = BODY_UNITS
# 可参与趋势图的实际维度（基础 + 围度；身高/颈围/肩宽按页面整改口径不参与趋势）
TREND_KEYS = [
    k
    for k in BODY_KEYS
    if BODY_FIELDS[k][3] in ("basic", "girth") and k not in ("height", "neck", "shoulder_width")
]
# 页面 4 指标卡
CARD_KEYS = ["weight", "body_fat", "waist", "hip"]
# 围度参与剪影标注
SILHOUETTE_METRICS = ["chest", "arm", "waist", "hip", "thigh"]

# ---------- 趋势聚合（BD-10~14） ----------
TREND_RANGES = ["week", "month", "two_month", "half_year", "year"]
# 两月档：以今天为末点向前共 60 天（含今天），逐日取当日记录值，不做窗口均值
TWO_MONTH_SPAN_DAYS = 60
# 半年锚点：每月 1/10/20 号；窗口 [锚点-10天, 锚点] 含两端共 11 天（需求定稿口径）
HALF_YEAR_ANCHOR_DAYS = (1, 10, 20)
HALF_YEAR_WINDOW_BACK = 10
# 年锚点：每月 1/15 号；窗口 [锚点-15天, 锚点] 含两端共 16 天
YEAR_ANCHOR_DAYS = (1, 15)
YEAR_WINDOW_BACK = 15

# ---------- 训练状态机（TR） ----------
TR_STATUS_PLANNED = "planned"
TR_STATUS_RECORDED = "recorded"

# ---------- 泳姿（SW） ----------
SWIM_STROKES = ["freestyle", "breaststroke", "backstroke", "butterfly", "mixed"]
SWIM_STROKE_LABELS = {
    "freestyle": "自由泳",
    "breaststroke": "蛙泳",
    "backstroke": "仰泳",
    "butterfly": "蝶泳",
    "mixed": "混合",
}

# ---------- 生理周期（MC） ----------
DEFAULT_CYCLE_LENGTH = 28
DEFAULT_PERIOD_LENGTH = 5
# 排卵日 = 段长 - 该偏移（黄体期固定 14 天，锚定下一次月经首日）
OVULATION_OFFSET = 14
# period_setting 仅作参考值：用于当前段、预测段与补推段，不参与真实段推算
REFERENCE_CYCLE_MIN = 22
REFERENCE_CYCLE_MAX = 45
REFERENCE_PERIOD_MIN = 2
REFERENCE_PERIOD_MAX = 8
# 段长约束：段长 = 相邻两次月经首日间隔（真实段）。
# 下限另受「经期天数 + OVULATION_OFFSET + 1」约束，保证排卵日不落进经期。
MIN_SEGMENT_DAYS = 22
MAX_SEGMENT_DAYS = 45
# 超过 3 个月（90 天）没有记录则不补推
GAP_INFER_MAX_DAYS = 90
# 预测起点逾期宽限：超过该天数转「未推算」，提示补录
PREDICT_GRACE_DAYS = 7
# 段来源：真实记录 / 漏记补推 / 最新记录后的当前段 / 下一个预测段
SEGMENT_RECORDED = "recorded"
SEGMENT_INFERRED = "inferred"
SEGMENT_CURRENT = "current"
SEGMENT_PREDICTED = "predicted"
# 排卵后区间：前/后期、黄体前/中/后期天数区间（排卵后第 N 天）
OVULATION_POST_PRE = 1  # 排卵期后期：排卵后 1~2 天
OVULATION_POST_POST = 2
LUTEAL_EARLY_END = 6    # 黄体期前期：排卵后 3~6 天
LUTEAL_MID_END = 10     # 黄体期中期：排卵后 7~10 天

# 七阶段独立枚举（禁止合并）
PHASE_MENSTRUAL = "menstrual"
PHASE_FOLLICULAR_PRE = "follicular_pre"
PHASE_OVULATION_DAY = "ovulation_day"
PHASE_FOLLICULAR_POST = "follicular_post"
PHASE_LUTEAL_EARLY = "luteal_early"
PHASE_LUTEAL_MID = "luteal_mid"
PHASE_LUTEAL_LATE = "luteal_late"
PHASE_KEYS = [
    PHASE_MENSTRUAL,
    PHASE_FOLLICULAR_PRE,
    PHASE_OVULATION_DAY,
    PHASE_FOLLICULAR_POST,
    PHASE_LUTEAL_EARLY,
    PHASE_LUTEAL_MID,
    PHASE_LUTEAL_LATE,
]
PHASE_LABELS = {
    PHASE_MENSTRUAL: "月经期",
    PHASE_FOLLICULAR_PRE: "排卵期前期",
    PHASE_OVULATION_DAY: "排卵日",
    PHASE_FOLLICULAR_POST: "排卵期后期",
    PHASE_LUTEAL_EARLY: "黄体期前期",
    PHASE_LUTEAL_MID: "黄体期中期",
    PHASE_LUTEAL_LATE: "黄体期后期",
}
# 阶段激素文案（MC-14）：每阶段两份（a 前段 / b 后段）。
# 阶段天数 n 按前半 floor(n/2)、后半剩余拆分；n=1 时只有 a 可用。
# 每份 70 字以内，两句话各占一行：上行客观激素状态，下行对心情 / 食欲 / 运动的影响。
PHASE_HORMONE = {
    PHASE_MENSTRUAL: (
        "雌激素、孕激素处于最低谷，前列腺素升高引起子宫收缩。\n易出现腹痛乏力、食欲下降和情绪低落，运动宜轻缓。",
        "雌激素开始回升，孕激素仍低，前列腺素逐步回落。\n体力和食欲逐渐恢复，情绪趋稳，可慢慢增加运动量。",
    ),
    PHASE_FOLLICULAR_PRE: (
        "雌激素稳步上升，FSH 促进卵泡发育，孕激素维持低位。\n精力与心情回升，食欲平稳，力量耐力逐步走高。",
        "雌激素接近高峰，LH 开始抬头，卵泡趋于成熟。\n状态接近最佳，食欲稳定，适合安排更高强度训练。",
    ),
    PHASE_OVULATION_DAY: (
        "LH 骤升触发排卵，雌激素达峰后快速回落。\n爆发力和心情处于高位，食欲平稳，但韧带松弛、关节稳定性下降。",
        "排卵瞬间雌激素短暂回落，孕激素开始缓慢上升。\n可能有一侧下腹轻微刺痛，精力仍好，运动注意热身。",
    ),
    PHASE_FOLLICULAR_POST: (
        "雌激素从峰值回落，孕激素开始上升，基础体温略升。\n精力尚可但易疲劳，情绪偏敏感，注意补水与休息。",
        "孕激素继续升高，雌激素下行，体温维持高位。\n体能开始下滑，食欲略增，运动宜降低强度、延长热身。",
    ),
    PHASE_LUTEAL_EARLY: (
        "孕激素明显升高，雌激素维持中等水平，体温偏高。\n心率偏快、耐热下降，情绪较稳，食欲略有增加。",
        "孕激素继续攀升，水钠潴留出现，体温处于高位。\n易有轻微水肿和疲惫，食欲上升，训练可适当减量。",
    ),
    PHASE_LUTEAL_MID: (
        "孕激素接近峰值，雌激素二次小幅升高，血清素下降。\n情绪波动、食欲增强较明显，体力一般，适合中等强度运动。",
        "孕激素达峰后回落，雌激素下行，代谢率略升。\n容易烦躁、嗜甜和水肿，运动表现下滑，需控制强度。",
    ),
    PHASE_LUTEAL_LATE: (
        "雌孕激素同步快速下降，前列腺素开始升高。\nPMS 症状明显，易低落、腹胀、食欲波动，运动以舒缓为主。",
        "雌孕激素降至最低，子宫内膜准备脱落，前列腺素升高。\n可能出现腹痛、疲惫和情绪低落，食欲下降，宜休息或轻度活动。",
    ),
}
# 经期状态（月历标注口径）：
# recorded=真实记录窗口内；inferred=过去漏记段按参考值补推出的经期；predicted=未来预测段经期。
PERIOD_STATE_RECORDED = "recorded"
PERIOD_STATE_INFERRED = "inferred"
PERIOD_STATE_PREDICTED = "predicted"
PERIOD_STATE_LABELS = {
    PERIOD_STATE_RECORDED: "经期",
    PERIOD_STATE_INFERRED: "推算经期",
    PERIOD_STATE_PREDICTED: "预测经期",
}

# ---------- 运动四档（MC-10） ----------
SPORT_HIGH = "high"
SPORT_GOOD = "good"
SPORT_AVERAGE = "average"
SPORT_REST = "rest"
SPORT_LABELS = {
    SPORT_HIGH: "精力旺盛",
    SPORT_GOOD: "状态良好",
    SPORT_AVERAGE: "状态一般",
    SPORT_REST: "适合休息",
}

# ---------- 疼痛等级（MC-03：0无痛/1轻度/2中度/3重度） ----------
PAIN_LEVELS = [0, 1, 2, 3]
PAIN_LABELS = {0: "无", 1: "轻度", 2: "中度", 3: "重度"}
# 原型疼痛按钮组 → 存储等级映射（MC-03 四档，UI 六按钮）
PAIN_BUTTONS = [
    ("无", 0),
    ("轻微", 1),
    ("轻度", 1),
    ("中等", 2),
    ("偏重", 2),
    ("严重", 3),
]

# ---------- 通用 ----------
def today_local() -> date:
    return date.today()


def monday_of(date_: date) -> date:
    return date_ - timedelta(days=date_.weekday())
