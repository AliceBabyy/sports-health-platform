"""模型注册中心：汇总 import 各模块 models，供 Base.metadata.create_all 建全部表。"""
from app.modules.auth.models import User  # noqa: F401
from app.modules.body.models import (  # noqa: F401
    BodyBasicGoalRecord,
    BodyBasicRecord,
    BodyDimensionsGoalRecord,
    BodyDimensionsRecord,
)
from app.modules.training.models import TrainingNote, TrainingRecord, TrainingRecordItem  # noqa: F401
from app.modules.swim.models import SwimNote, SwimRecord  # noqa: F401
from app.modules.dance.models import DanceNote, DanceRecord  # noqa: F401
from app.modules.cycle.models import PeriodLog, PeriodRecord, PeriodSetting  # noqa: F401
from app.modules.state_record.models import (  # noqa: F401
    AppetiteRecord,
    InflammationRecord,
    MoodRecord,
    MyalgiaRecord,
)
from app.modules.agent.models import (  # noqa: F401
    AgentConversation,
    AgentPersona,
    AgentPersonaVersion,
    AgentSkill,
    AgentSkillRun,
    AgentSkillVersion,
)
from app.modules.profile.models import HealthProfile  # noqa: F401
from app.modules.report.models import Report  # noqa: F401
from app.modules.daily_advice.models import DailyAdvice  # noqa: F401
from app.modules.system.scheduler.models import JobRun, ScheduledJob  # noqa: F401
