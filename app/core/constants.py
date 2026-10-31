"""全局常量与枚举：指标 key、泳姿、训练状态机、周期七阶段、运动三档、疼痛等级、趋势档位。

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
# 可参与趋势图的实际维度（基础 + 围度，排除两组目标值）
TREND_KEYS = [k for k in BODY_KEYS if BODY_FIELDS[k][3] in ("basic", "girth")]
# 页面 4 指标卡
CARD_KEYS = ["weight", "body_fat", "waist", "hip"]
# 围度参与剪影标注
SILHOUETTE_METRICS = ["chest", "arm", "waist", "hip", "thigh"]

# ---------- 趋势聚合（BD-10~14） ----------
TREND_RANGES = ["week", "month", "half_year", "year"]
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
# 排卵日 = 周期长度 - 该偏移（需求 7.2：N = 周期长度 - 14）
OVULATION_OFFSET = 14
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
# 阶段说明总表（MC-13）：周期区间 / 激素特征 / 运动建议 / 状态倾向
PHASE_INFO = {
    PHASE_MENSTRUAL: {
        "range": "第1~5天",
        "hormone": "雌激素、孕激素双低，前列腺素升高",
        "advice": "体温偏低，铁流失增加。以下肢拉伸、呼吸训练替代下肢大重量。",
        "level": "rest",
    },
    PHASE_FOLLICULAR_PRE: {
        "range": "第6~13天",
        "hormone": "雌激素快速上升，FSH促进卵泡成熟",
        "advice": "力量耐受度上升，适合把深蹲、硬拉等大重量安排在这周。",
        "level": "high",
    },
    PHASE_OVULATION_DAY: {
        "range": "第14天",
        "hormone": "LH峰值，雌激素达到顶点，基础体温将回升",
        "advice": "周期中运动表现峰值，可安排PR冲刺或高强度间歇。",
        "level": "high",
    },
    PHASE_FOLLICULAR_POST: {
        "range": "第15~16天",
        "hormone": "LH峰值附近，雌激素维持高位",
        "advice": "爆发力最佳但韧带松弛度升高，注意落地缓冲与膝踝稳定。",
        "level": "high",
    },
    PHASE_LUTEAL_EARLY: {
        "range": "第17~20天",
        "hormone": "孕激素上升，基础体温升高0.3-0.5℃",
        "advice": "心率与体温偏高，同等强度下RPE更高，适当降5-10%负荷。",
        "level": "good",
    },
    PHASE_LUTEAL_MID: {
        "range": "第21~24天",
        "hormone": "孕激素达峰，血清素下降",
        "advice": "易出现水肿与食欲波动，训练以中等强度稳态有氧为主。",
        "level": "good",
    },
    PHASE_LUTEAL_LATE: {
        "range": "第25~28天",
        "hormone": "雌孕激素同步回落，前列腺素开始升高",
        "advice": "PMS高发窗口，改为瑜伽、游泳或散步，保证睡眠优先。",
        "level": "rest",
    },
}
# 排卵日/排卵期前后（雌激素峰值）→ 精力旺盛判定区间
HIGH_LEVEL_PHASES = {PHASE_FOLLICULAR_PRE, PHASE_OVULATION_DAY, PHASE_FOLLICULAR_POST}
# 状态良好判定区间（排卵期前期/黄体期前中期）
GOOD_LEVEL_PHASES = {PHASE_FOLLICULAR_PRE, PHASE_LUTEAL_EARLY, PHASE_LUTEAL_MID}

# ---------- 运动三档（MC-10） ----------
SPORT_HIGH = "high"
SPORT_GOOD = "good"
SPORT_REST = "rest"
SPORT_LABELS = {SPORT_HIGH: "精力旺盛", SPORT_GOOD: "状态良好", SPORT_REST: "适合休息"}

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
