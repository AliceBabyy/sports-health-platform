"""AI Agent 会话与角色表：会话元数据、LangGraph 线程映射、多角色 Persona。

消息不建独立表，由 PostgresSaver checkpointer 持久化在框架表（schema langgraph）；
会话表只存归属、标题、模型、thread_id 与角色绑定（普通会话 persona 两列为空）。
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

DEFAULT_TITLE = "新会话"
TITLE_MAX_CHARS = 64
AUTO_TITLE_LEN = 12


class AgentConversation(Base):
    __tablename__ = "agent_conversations"
    __table_args__ = (
        CheckConstraint(
            "((persona_id IS NULL) = (persona_version_no IS NULL))",
            name="ck_agent_conversations_persona",
        ),
        Index("ix_agent_conversations_user_last", "user_id", text("last_message_at DESC")),
        {"comment": "AI Agent 会话（元数据 + LangGraph thread_id + 角色绑定；消息由 checkpointer 管理）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        comment="用户 FK，删除账号时级联删除",
    )
    title: Mapped[str] = mapped_column(
        String(TITLE_MAX_CHARS), nullable=False, default=DEFAULT_TITLE, server_default=DEFAULT_TITLE,
        comment="会话标题（首条消息取前 12 字，默认新会话）",
    )
    model_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="会话级模型（可空，用默认模型）",
    )
    persona_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_personas.id"), nullable=True,
        comment="角色会话绑定的角色 FK；普通会话为空，创建后不可切换",
    )
    persona_version_no: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="创建会话时绑定的角色版本号，保证历史会话不随角色改版漂移",
    )
    thread_id: Mapped[UUID] = mapped_column(
        Uuid, nullable=False, unique=True, comment="LangGraph 线程 ID（checkpointer 键）",
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="最近消息时间（列表排序冗余）",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
        comment="更新时间（ORM onupdate 自动刷新）",
    )


PERSONA_SCOPES = ("system", "user")
PERSONA_STATUSES = ("active", "disabled")


class AgentPersona(Base):
    """角色主表：平台内置角色（scope=system）与用户自定义角色（scope=user）。

    角色只保存人设提示词和角色级授权：tool_grants / skill_grants 为空表示沿用平台
    默认范围（TOOL_PERSONA_SCOPES 等代码基线），非空表示管理员显式勾选的白名单。
    """
    __tablename__ = "agent_personas"
    __table_args__ = (
        CheckConstraint("scope IN ('system', 'user')", name="ck_agent_personas_scope"),
        CheckConstraint(
            "(scope = 'system' AND owner_user_id IS NULL) "
            "OR (scope = 'user' AND owner_user_id IS NOT NULL)",
            name="ck_agent_personas_owner",
        ),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_agent_personas_status"),
        Index("uq_agent_personas_system_key", "persona_key", unique=True,
              postgresql_where=text("scope = 'system'"), sqlite_where=text("scope = 'system'")),
        Index("uq_agent_personas_user_key", "owner_user_id", "persona_key", unique=True,
              postgresql_where=text("scope = 'user'"), sqlite_where=text("scope = 'user'")),
        Index("ix_agent_personas_list", "scope", "status", "sort_order"),
        {"comment": "AI 角色（平台内置角色 + 用户私有自定义提示词角色；含角色级工具/技能白名单）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    scope: Mapped[str] = mapped_column(String(16), nullable=False, comment="归属：system / user")
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
        comment="用户角色归属；平台内置角色为空",
    )
    persona_key: Mapped[str] = mapped_column(String(48), nullable=False, comment="稳定键，供种子幂等与后续工具授权使用")
    name: Mapped[str] = mapped_column(String(48), nullable=False, comment="角色显示名")
    description: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", comment="角色定位，供列表展示与人设段渲染",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active",
        comment="状态：active / disabled（停用后不可新建角色会话，已有会话仍可继续）",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="平台角色排序；用户角色不参与",
    )
    current_version_no: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="当前生效版本号；未发布为空",
    )
    tool_grants: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True,
        comment="角色可用工具白名单 JSON 数组；NULL=按平台默认范围，空数组=不使用工具",
    )
    skill_grants: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True,
        comment="角色可用平台技能白名单 JSON 数组；NULL=全部平台技能，空数组=不使用技能",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")


class AgentPersonaVersion(Base):
    """角色版本：定义固定为 {schema_version, prompt}；保存即生成新版本并立即生效。"""
    __tablename__ = "agent_persona_versions"
    __table_args__ = (
        Index("uq_agent_persona_versions_no", "persona_id", "version_no", unique=True),
        {"comment": "AI 角色版本（人设提示词定义与发布快照）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    persona_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agent_personas.id", ondelete="CASCADE"), nullable=False, comment="角色 FK",
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号，从 1 递增")
    definition: Mapped[dict] = mapped_column(JSON, nullable=False, comment="角色定义 JSON：{schema_version, prompt}")
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", comment="定义 SHA-256，便于审计")
    validation: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="最近一次校验结果（errors/warnings）")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="创建人 user_id")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="生效时间；NULL 表示草稿")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")


SKILL_SCOPES = ("system", "user")
SKILL_KINDS = ("code", "declarative", "prompt")
SYSTEM_SKILL_KINDS = ("code", "declarative")
USER_SKILL_KINDS = ("prompt",)
SKILL_STATUSES = ("draft", "active", "disabled", "archived")


class AgentSkill(Base):
    """技能主表：系统技能（scope=system，owner 为空）与用户私有技能（scope=user）。"""
    __tablename__ = "agent_skills"
    __table_args__ = (
        CheckConstraint("scope IN ('system', 'user')", name="ck_agent_skills_scope"),
        CheckConstraint(
            "((scope = 'system' AND kind IN ('code', 'declarative')) "
            "OR (scope = 'user' AND kind = 'prompt'))",
            name="ck_agent_skills_scope_kind",
        ),
        CheckConstraint("status IN ('draft', 'active', 'disabled', 'archived')", name="ck_agent_skills_status"),
        Index("uq_agent_skills_system_key", "skill_key", unique=True,
              postgresql_where=text("scope = 'system'"), sqlite_where=text("scope = 'system'")),
        Index("uq_agent_skills_user_key", "owner_user_id", "skill_key", unique=True,
              postgresql_where=text("scope = 'user'"), sqlite_where=text("scope = 'user'")),
        Index("uq_agent_skills_user_alias", "owner_user_id", "slash_alias", unique=True,
              postgresql_where=text("scope = 'user' AND slash_alias IS NOT NULL"),
              sqlite_where=text("scope = 'user' AND slash_alias IS NOT NULL")),
        Index("ix_agent_skills_owner", "owner_user_id"),
        {"comment": "AI 技能（平台只读 code/declarative + 用户私有提示词技能）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    scope: Mapped[str] = mapped_column(String(16), nullable=False, comment="归属：system / user")
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
        comment="用户技能归属；系统技能为空",
    )
    skill_key: Mapped[str] = mapped_column(String(48), nullable=False, comment="稳定键，工具名为 skill_<key>")
    name: Mapped[str] = mapped_column(String(48), nullable=False, comment="技能显示名")
    description: Mapped[str] = mapped_column(String(200), nullable=False, default="", comment="能力描述，供模型选择与页面展示")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default="prompt", comment="实现类型：system 为 code/declarative，user 为 prompt")
    category: Mapped[str] = mapped_column(String(16), nullable=False, default="custom", server_default="custom",
                                          comment="分类：body / swim / custom")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft",
                                        comment="状态：draft / active / disabled / archived")
    slash_alias: Mapped[str | None] = mapped_column(String(24), nullable=True, comment="斜杠别名（可空，如 体脂腰围）")
    current_version_no: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="当前发布版本号；未发布为空")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")


class AgentSkillVersion(Base):
    """技能版本：声明式定义或代码技能元信息；每次保存草稿新增一版，发布后固化。"""
    __tablename__ = "agent_skill_versions"
    __table_args__ = (
        Index("uq_agent_skill_versions_skill_no", "skill_id", "version_no", unique=True),
        {"comment": "AI 技能版本（平台声明式 DSL / 用户提示词 / 代码技能元信息）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    skill_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agent_skills.id", ondelete="CASCADE"), nullable=False, comment="技能 FK",
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号，从 1 递增")
    definition: Mapped[dict] = mapped_column(JSON, nullable=False, comment="定义 JSON（平台声明式 DSL、用户提示词或代码技能元信息）")
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", comment="定义 SHA-256，便于审计")
    validation: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="最近一次校验结果（errors/warnings）")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="创建人 user_id")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="发布时间；NULL 表示草稿")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")


class AgentSkillRun(Base):
    """技能运行审计：解析、执行、失败与配额记录。"""
    __tablename__ = "agent_skill_runs"
    __table_args__ = (
        Index("ix_agent_skill_runs_skill_created", "skill_id", text("created_at DESC")),
        Index("ix_agent_skill_runs_user_created", "user_id", text("created_at DESC")),
        {"comment": "AI 技能运行审计（参数解析、执行结果、失败与配额）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    skill_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agent_skills.id", ondelete="CASCADE"), nullable=False, comment="技能 FK",
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="执行版本号")
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="调用用户",
    )
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="会话 ID（试运行为空）")
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, server_default="model",
                                          comment="触发方式：slash / model / test")
    status: Mapped[str] = mapped_column(String(16), nullable=False, comment="结果：ok / insufficient_data / invalid_args / failed")
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True, comment="失败错误码")
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="失败信息")
    args: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="归一化后的参数")
    parse: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="参数解析元信息（strategy/model/prompt_version/elapsed_ms/warnings）")
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="样本条数")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="执行耗时 ms")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
