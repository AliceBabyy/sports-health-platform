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


settings = Settings()
