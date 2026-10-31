"""模型注册中心：汇总 import 各模块 models，供 Base.metadata.create_all 建全部表。"""
from app.modules.auth.models import User  # noqa: F401
from app.modules.body.models import (  # noqa: F401
    BodyBasicGoalRecord,
    BodyBasicRecord,
    BodyDimensionsGoalRecord,
    BodyDimensionsRecord,
)
from app.modules.training.models import TrainingNote, TrainingPlan, TrainingPlanItem  # noqa: F401
from app.modules.swim.models import SwimRecord  # noqa: F401
from app.modules.dance.models import DanceRecord  # noqa: F401
from app.modules.cycle.models import CycleSetting, DailyPainLog, PeriodRecord  # noqa: F401
