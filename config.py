"""全局配置：从 .env 读取（pydantic-settings）。"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = (
        "postgresql+psycopg2://postgres:123456@127.0.0.1:5432/sports-health-platform"
    )
    secret_key: str = "dev-secret-key-change-me"
    port: int = 8010
    session_cookie_secure: bool = False
    session_cookie_name: str = "sh_session"


settings = Settings()
