"""全局配置：从 .env 读取（pydantic-settings）。"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = (
        "postgresql+psycopg2://postgres:123456@127.0.0.1:5432/sports-health-platform"
    )
    secret_key: str = "dev-secret-key-change-me"
    host: str = "0.0.0.0"
    port: int = 8010
    session_cookie_secure: bool = False
    session_cookie_name: str = "sh_session"
    ai_api_key: str = ""
    ai_base_url: str = "https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1"
    ai_default_model: str = "deepseek-v4.1-flash"
    ai_timeout_seconds: float = 30.0
    ai_max_retries: int = 1
    # AI 导入（2026-11-10）：纯文字与带图分别选模型；图片限制由后端兜底
    ai_import_model: str = "qwen3.8-flash"
    ai_import_vision_model: str = "qwen3-vl-plus"
    ai_import_timeout_seconds: float = 60.0
    ai_import_max_images: int = 3
    ai_import_max_image_bytes: int = 2 * 1024 * 1024
    ai_import_max_prompt_chars: int = 2000
    # AI Agent（V2.2 基础问答）：流式 SSE、上下文 token 预算、checkpointer 独立 schema
    agent_stream_enabled: bool = True
    agent_context_token_budget: int = 12000
    agent_checkpointer_schema: str = "langgraph"
    agent_max_input_chars: int = 2000
    agent_pool_min_size: int = 1
    agent_pool_max_size: int = 10
    # 多角色（V2.4）：用户私有角色配额与人设提示词长度上限
    agent_persona_max_per_user: int = 10
    agent_persona_max_chars: int = 2000
    # AI 运动报告（2026-11-17）：周报周一生成上周、月报每月 1 日生成上月；
    # 自动触发由应用内调度器完成（见下方 scheduler_*），不再依赖操作系统计划任务。
    report_auto_enabled: bool = True
    report_model: str = ""  # 留空用 ai_default_model
    report_timeout_seconds: float = 60.0
    # 报告走非流式结构化输出，长思考模型会顶满读超时；默认对 qwen* 关闭思考
    report_enable_thinking: bool = False
    report_max_attempts: int = 3
    # 侧栏每日训练建议（V2.8）：00:01 生成当天一份；启动后补跑当天缺失的行
    advice_auto_enabled: bool = True
    advice_timeout_seconds: float = 30.0
    advice_max_attempts: int = 3
    # 启动补跑延迟秒数；0 表示不补跑（错过仍可手动刷新）
    advice_startup_catchup_seconds: int = 60
    # 角色与管理员区（2026-11-19）：`/system` 与 `/api/system` 仅管理员可访问；
    # 无管理员时启动自动提升 user_id 最小的启用账号，配置项可按登录名追加指定管理员（逗号分隔）
    admin_usernames: str = ""
    # 应用内定时任务（2026-11-17）：APScheduler 后台线程 + scheduled_jobs 表
    scheduler_enabled: bool = True
    scheduler_timezone: str = "Asia/Shanghai"
    # 错过宽限：超过该秒数仍未执行则跳过并记 skipped，由页面手动补跑
    scheduler_misfire_grace_seconds: int = 300


settings = Settings()
