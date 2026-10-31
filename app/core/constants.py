"""全局常量与枚举：指标 key、泳姿、训练状态机、周期七阶段、运动三档、疼痛等级、趋势档位。

魔法值（窗口天数、周期默认值、阶段边界）集中在这里，改动只动常量、不动接口。
"""
from datetime import date, timedelta

# ---------- 身材指标 ----------
# 需求 BD-01 七指标 + UI 原型体脂率（规划 12.1 建议加入第 8 个 key）
METRIC_KEYS = ["height", "weight", "body_fat", "chest", "arm", "waist", "hip", "thigh"]
METRIC_LABELS = {
    "height": "身高",
    "weight": "体重",
    "body_fat": "体脂率",
    "chest": "胸围",
    "arm": "手臂围",
    "waist": "腰围",
    "hip": "臀围",
    "thigh": "大腿围",
}
METRIC_UNITS = {
    "height": "cm",
    "weight": "kg",
    "body_fat": "%",
    "chest": "cm",
    "arm": "cm",
    "waist": "cm",
    "hip": "cm",
    "thigh": "cm",
}
# 身高/体重为固定双卡位，围度参与剪影标注
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
