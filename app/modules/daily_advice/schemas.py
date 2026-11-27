"""每日训练建议的结构化输出与接口入参。"""
from datetime import date as date_type

from pydantic import BaseModel, ConfigDict, Field


class DailyAdvice(BaseModel):
    """模型结构化输出：三段可扩展判断 + 健身部位 + 五段正文。extra=forbid 防止模型自造字段。"""

    model_config = ConfigDict(extra="forbid")

    verdict: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^(适合但收敛|适合|克制|休息)",
        description=(
            "今天适不适合运动。必须以「适合」「适合但收敛」「克制」「休息」之一开头，"
            "再用「：」补充条件，例如「适合：上肢正常，下肢先收着」；不要只写一个档位"
        ),
    )
    focus: str = Field(
        min_length=2,
        max_length=120,
        description=(
            "今天的训练安排，可自由写动作方向、目标部位、避开部位与运动类型，"
            "例如「上肢推拉 + 15分钟轻松有氧，避开肩背和腿」；不要只写有氧/无氧"
        ),
    )
    intensity: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^(很低|低|中|高|很高)",
        description=(
            "建议强度。必须以「很低」「低」「中」「高」「很高」之一开头，"
            "再用「：」补充 RPE、心率或时长口径，例如「低：RPE 3~4，30分钟，能正常对话」"
        ),
    )
    body_parts: list[str] = Field(default_factory=list, description="今天建议练的健身部位，最多 2 个")
    text: str = Field(
        description=(
            "侧栏五句话（一句一行）：今日判断与强度 / 训练安排 / 最近一次健身播报 / "
            "结合健康档案与今日状态的贴心提示 / 简短鼓励；不加小标题、编号或固定前缀"
        )
    )


class AdviceRegenerateIn(BaseModel):
    """手动刷新入参：默认今天，force 强制重算。"""

    model_config = ConfigDict(extra="forbid")

    date: date_type | None = None
    force: bool = False
