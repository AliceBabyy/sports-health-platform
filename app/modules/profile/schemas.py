"""个人信息 schemas：基本资料更新 / 修改密码 / 健康档案逐题保存请求体。"""
from pydantic import BaseModel, ConfigDict, Field


class ProfileUpdateIn(BaseModel):
    display_name: str
    gender: str = ""
    age: str = ""


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


class AccountDeleteIn(BaseModel):
    mode: str
    current_password: str


class HealthProfileItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_id: str = Field(min_length=1, max_length=16, description="档案套 id")
    local_key: str = Field(pattern=r"^q(?:[1-9]|10)$", description="套内题号 q1~q10")
    answer: str = Field(default="", max_length=255, description="文本答案，可空")


class HealthProfileIn(BaseModel):
    """页面保存：按 (set_id, local_key) 逐题更新已存储档案，空串表示清空该题。"""

    model_config = ConfigDict(extra="forbid")

    items: list[HealthProfileItemIn] = Field(default_factory=list, max_length=200)


class HealthProfileQuestionIn(BaseModel):
    """页面新增/编辑弹窗中的一道题：问题、回答和内部排序字段一起提交。"""

    model_config = ConfigDict(extra="forbid")

    local_key: str = Field(pattern=r"^q(?:[1-9]|10)$", description="套内题号 q1~q10")
    aspect: str = Field(min_length=1, max_length=32, description="专项内方面")
    label: str = Field(min_length=1, max_length=48, description="问题标题")
    hint: str = Field(default="", max_length=120, description="填写提示，可空")
    placeholder: str = Field(default="", max_length=120, description="占位文案，可空")
    max_length: int = Field(default=200, ge=50, le=255, description="答案最大字数")
    answer: str = Field(default="", max_length=255, description="文本答案，可空")


class HealthProfileSetIn(BaseModel):
    """页面新增/编辑一整套专项：允许 1~10 题，保存后原地刷新该卡。"""

    model_config = ConfigDict(extra="forbid")

    skill_key: str = Field(default="", max_length=64, description="专项 key；编辑已有套时可空")
    questions: list[HealthProfileQuestionIn] = Field(min_length=1, max_length=10)
