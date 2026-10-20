from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


BASE_SETTINGS_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)


class BaseHTTPClientConfig(BaseSettings):
    BASE_URL: str = ""
    KEEP_ALIVE_CONNECTIONS: int = 10
    MAX_CONNECTIONS: int = 20
    MAX_RETRIES: int = 2                            # retries after the first attempt
    TIMEOUT: float = 30.0

    def auth_headers(self) -> dict[str, str]:
        return {}                                   # subclasses override per system


class DBConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_", **BASE_SETTINGS_CONFIG)
    DRIVER: str = "postgresql+asyncpg"              # async driver by default
    HOST: str = "localhost"
    PORT: int = 5432
    USER: str = "postgres"
    PASSWORD: str = "password"
    NAME: str = "postgres"
    POOL_SIZE: int = 5
    POOL_OVERFLOW: int = 10
    POOL_RECYCLE: int = 3600
    ECHO: bool = False

    @property
    def url(self) -> URL:
        return URL.create(
            drivername=self.DRIVER,
            username=self.USER,
            password=self.PASSWORD,
            host=self.HOST,
            port=self.PORT,
            database=self.NAME,
        )

    def sync_url(self, driver: str = "postgresql") -> URL:
        return self.url.set(drivername=driver)      # for Alembic + test bootstrap

    @property
    def PATH(self) -> str:
        return f"{self.HOST}:{self.PORT}/{self.NAME}"


class OpenAIConfig(BaseHTTPClientConfig):
    model_config = SettingsConfigDict(env_prefix="OPENAI_", **BASE_SETTINGS_CONFIG)
    BASE_URL: str = "https://api.openai.com"
    API_KEY: str
    MODEL: str = "gpt-4o-mini"

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.API_KEY}"}


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", **BASE_SETTINGS_CONFIG)
    ENV: Literal["local", "test", "dev", "staging", "production"] = "local"
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    NAME: str = "My Service"
    VERSION: str = "1.0.0"
    DEBUG: bool = False
    CORS_ORIGINS: list[str] = []                    # exact browser origins; empty = no CORS

    db: DBConfig = Field(default_factory=DBConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
