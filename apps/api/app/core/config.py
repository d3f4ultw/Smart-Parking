from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Configuracion de ejecucion cargada desde el entorno del proceso."""

    database_host: str = Field(min_length=1, validation_alias="DATABASE_HOST")
    database_port: int = Field(
        ge=1,
        le=65_535,
        validation_alias="DATABASE_PORT",
    )
    database_name: str = Field(min_length=1, validation_alias="DATABASE_NAME")
    database_user: str = Field(min_length=1, validation_alias="DATABASE_USER")
    database_password: SecretStr = Field(validation_alias="DATABASE_PASSWORD")
    smtp_host: str | None = Field(default=None, validation_alias="SMTP_HOST")
    # Los campos SMTP se conservan como texto; solo se validan si SMTP esta activo.
    smtp_port: str | None = Field(default="465", validation_alias="SMTP_PORT")
    smtp_username: str | None = Field(
        default=None,
        validation_alias="SMTP_USERNAME",
    )
    smtp_password: SecretStr | None = Field(
        default=None,
        validation_alias="SMTP_PASSWORD",
    )
    smtp_from_email: str | None = Field(
        default=None,
        validation_alias="SMTP_FROM_EMAIL",
    )
    smtp_from_name: str = Field(
        default="Smart Parking",
        validation_alias="SMTP_FROM_NAME",
    )
    smtp_security: str = Field(default="ssl", validation_alias="SMTP_SECURITY")
    smtp_timeout_seconds: str | None = Field(
        default="10",
        validation_alias="SMTP_TIMEOUT_SECONDS",
    )
    app_public_url: str = Field(
        default="http://localhost:3000",
        validation_alias="APP_PUBLIC_URL",
    )
    app_environment: Literal["development", "production"] = Field(
        default="development",
        validation_alias="APP_ENVIRONMENT",
    )
    correo_transporte: Literal["smtp"] = Field(
        default="smtp",
        validation_alias="CORREO_TRANSPORTE",
    )
    session_cookie_name: str = Field(
        default="smart_parking_session",
        validation_alias="SESSION_COOKIE_NAME",
    )
    session_duration_minutes: int = Field(
        default=480,
        ge=1,
        validation_alias="SESSION_DURATION_MINUTES",
    )
    activacion_reenvio_cooldown_segundos: int = Field(
        default=60,
        ge=1,
        le=86_400,
        validation_alias="ACTIVACION_REENVIO_COOLDOWN_SEGUNDOS",
    )
    activation_token_ttl_hours: int = Field(
        ge=1,
        le=168,
        validation_alias="ACTIVATION_TOKEN_TTL_HOURS",
    )
    activation_challenge_ttl_minutes: int = Field(
        ge=5,
        le=60,
        validation_alias="ACTIVATION_CHALLENGE_TTL_MINUTES",
    )

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def database_url(self) -> URL:
        """Construye la URL SQLAlchemy con componentes tipados y password opaco."""

        return URL.create(
            drivername="postgresql+psycopg",
            username=self.database_user,
            password=self.database_password.get_secret_value(),
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )

    @property
    def session_cookie_secure(self) -> bool:
        """Activa Secure unicamente cuando la aplicacion corre en produccion."""

        return self.app_environment == "production"


@lru_cache
def get_settings() -> Settings:
    # Pydantic completa los campos requeridos desde el entorno del proceso.
    return Settings()  # pyright: ignore[reportCallIssue]
