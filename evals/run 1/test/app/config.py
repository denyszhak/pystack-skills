from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

BASE_SETTINGS_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)


class BaseHTTPClientConfig(BaseSettings):
    BASE_URL: str = ""
    KEEP_ALIVE_CONNECTIONS: int = 10
    MAX_CONNECTIONS: int = 20
    MAX_RETRIES: int = 3
    TIMEOUT: float = 30.0

    def auth_headers(self) -> dict[str, str]:
        return {}


class DBConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_", **BASE_SETTINGS_CONFIG)

    URL: str | None = None
    DRIVER: str = "postgresql+asyncpg"
    HOST: str = "localhost"
    PORT: int = 5432
    USER: str = "postgres"
    PASSWORD: str = "postgres"
    NAME: str = "invoices"
    POOL_SIZE: int = 5
    POOL_OVERFLOW: int = 10
    POOL_RECYCLE: int = 3600
    ECHO: bool = False
    AUTO_CREATE_TABLES: bool = False

    @property
    def url(self) -> URL:
        if self.URL is not None:
            return make_url(self.URL)
        return URL.create(
            drivername=self.DRIVER,
            username=self.USER,
            password=self.PASSWORD,
            host=self.HOST,
            port=self.PORT,
            database=self.NAME,
        )

    def sync_url(self, driver: str = "postgresql") -> URL:
        return self.url.set(drivername=driver)


class PaymentProviderConfig(BaseHTTPClientConfig):
    model_config = SettingsConfigDict(env_prefix="PAYMENT_PROVIDER_", **BASE_SETTINGS_CONFIG)

    BASE_URL: str = "https://payments.example.invalid/"
    API_KEY: str = ""

    def auth_headers(self) -> dict[str, str]:
        if not self.API_KEY:
            return {}
        return {"Authorization": f"Bearer {self.API_KEY}"}


class EmailProviderConfig(BaseHTTPClientConfig):
    model_config = SettingsConfigDict(env_prefix="EMAIL_PROVIDER_", **BASE_SETTINGS_CONFIG)

    BASE_URL: str = "https://email.example.invalid/"
    API_KEY: str = ""

    def auth_headers(self) -> dict[str, str]:
        if not self.API_KEY:
            return {}
        return {"Authorization": f"Bearer {self.API_KEY}"}


class OutboxConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OUTBOX_", **BASE_SETTINGS_CONFIG)

    ENABLED: bool = False
    POLL_INTERVAL_SECONDS: float = 1.0
    BATCH_SIZE: int = 100


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", **BASE_SETTINGS_CONFIG)

    ENV: Literal["local", "dev", "staging", "production", "test"] = "local"
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    NAME: str = "Invoice Collection Service"
    VERSION: str = "0.1.0"
    DEBUG: bool = False

    db: DBConfig = Field(default_factory=DBConfig)
    payment_provider: PaymentProviderConfig = Field(default_factory=PaymentProviderConfig)
    email_provider: EmailProviderConfig = Field(default_factory=EmailProviderConfig)
    outbox: OutboxConfig = Field(default_factory=OutboxConfig)
