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


settings = Settings()
