"""AI 配置三表 ORM 映射（表由 scripts/migrate_ai_config.py 建好）。

运行时 registry 用轻量 SQL 读快照；管理页用这里的 ORM 做增删改与引用校验。
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

# JSONB 仅在 PostgreSQL 生效；测试用 SQLite 时退化为 JSON
JSONDict = JSON().with_variant(JSONB, "postgresql")


class AiProvider(Base):
    __tablename__ = "ai_providers"
    __table_args__ = {"comment": "AI 模型来源（一个 base_url + 一套凭据）"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    provider_key: Mapped[str] = mapped_column(String(48), unique=True, comment="来源短标识")
    name: Mapped[str] = mapped_column(String(64), comment="来源显示名")
    base_url: Mapped[str] = mapped_column(String(255), comment="OpenAI 兼容接口地址")
    api_key_env: Mapped[str] = mapped_column(String(64), default="AI_API_KEY", comment="密钥环境变量名")
    api_key_cipher: Mapped[str | None] = mapped_column(String, nullable=True, comment="加密后的密钥")
    timeout_seconds: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=30, comment="默认读超时")
    max_retries: Mapped[int] = mapped_column(Integer, default=1, comment="默认重试次数")
    extra_headers: Mapped[dict] = mapped_column(JSONDict, default=dict, comment="附加请求头")
    status: Mapped[str] = mapped_column(String(16), default="active", comment="状态")
    remark: Mapped[str] = mapped_column(String(200), default="", comment="备注")
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="最近维护人")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    models: Mapped[list["AiModel"]] = relationship(back_populates="provider")


class AiModel(Base):
    __tablename__ = "ai_models"
    __table_args__ = {"comment": "AI 模型清单（业务别名 + 来源 + 上游模型名）"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    alias: Mapped[str] = mapped_column(String(64), unique=True, comment="业务别名")
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="RESTRICT"), comment="所属来源"
    )
    upstream_name: Mapped[str] = mapped_column(String(128), comment="上游模型名")
    supports_text: Mapped[bool] = mapped_column(Boolean, default=True, comment="文本")
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False, comment="图片输入")
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=False, comment="工具调用")
    supports_structured_output: Mapped[bool] = mapped_column(Boolean, default=True, comment="结构化输出")
    structured_method: Mapped[str] = mapped_column(String(24), default="json_schema", comment="结构化方式")
    timeout_seconds: Mapped[Decimal | None] = mapped_column(Numeric(6, 1), nullable=True, comment="模型级超时")
    extra_body: Mapped[dict] = mapped_column(JSONDict, default=dict, comment="附加请求体")
    params: Mapped[dict] = mapped_column(JSONDict, default=dict, comment="通用参数")
    selectable_for_chat: Mapped[bool] = mapped_column(Boolean, default=True, comment="对话下拉可选")
    status: Mapped[str] = mapped_column(String(16), default="active", comment="状态")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="排序")
    remark: Mapped[str] = mapped_column(String(200), default="", comment="备注")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    provider: Mapped[AiProvider] = relationship(back_populates="models")


class AiFeatureRoute(Base):
    __tablename__ = "ai_feature_routes"
    __table_args__ = {"comment": "AI 功能路由（一个功能点配一个模型别名）"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    feature_key: Mapped[str] = mapped_column(String(64), unique=True, comment="功能键")
    model_alias: Mapped[str] = mapped_column(String(64), comment="模型别名")
    timeout_seconds: Mapped[Decimal | None] = mapped_column(Numeric(6, 1), nullable=True, comment="功能点超时")
    params_override: Mapped[dict] = mapped_column(JSONDict, default=dict, comment="参数覆盖")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    remark: Mapped[str] = mapped_column(String(200), default="", comment="备注")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )
