import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
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
    vision_bearer_token: SecretStr | None = Field(
        default=None,
        validation_alias="VISION_BEARER_TOKEN",
    )
    vision_reference_frame_path: Path | None = Field(
        default=None,
        validation_alias="VISION_REFERENCE_FRAME_PATH",
    )
    vision_source_mode: Literal["simulation", "camera"] = Field(
        default="simulation",
        validation_alias="VISION_SOURCE_MODE",
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
    session_cookie_secure_override: bool | None = Field(
        default=None,
        validation_alias="SESSION_COOKIE_SECURE",
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
    customer_session_cookie_name: str = Field(
        default="smart_parking_customer_session",
        min_length=1,
        validation_alias="CUSTOMER_SESSION_COOKIE_NAME",
    )
    customer_session_duration_minutes: int = Field(
        default=480,
        ge=1,
        validation_alias="CUSTOMER_SESSION_DURATION_MINUTES",
    )
    customer_session_cookie_secure_override: bool | None = Field(
        default=None,
        validation_alias="CUSTOMER_SESSION_COOKIE_SECURE",
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
    parking_timezone: str = Field(
        default="America/Mexico_City",
        min_length=1,
        validation_alias="PARKING_TIMEZONE",
    )
    stripe_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="STRIPE_API_KEY",
    )
    stripe_webhook_secret: SecretStr | None = Field(
        default=None,
        validation_alias="STRIPE_WEBHOOK_SECRET",
    )
    stripe_membership_price_ids: str = Field(
        default="",
        validation_alias="STRIPE_MEMBERSHIP_PRICE_IDS",
    )

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("parking_timezone")
    @classmethod
    def validar_zona_horaria(cls, valor: str) -> str:
        """Exige una zona IANA disponible en los datos de horario de Python."""

        try:
            ZoneInfo(valor)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError(
                "PARKING_TIMEZONE debe ser una zona IANA válida."
            ) from error
        return valor

    @field_validator("stripe_api_key")
    @classmethod
    def validar_clave_stripe_sandbox(cls, valor: SecretStr | None) -> SecretStr | None:
        """Impide que una clave Live llegue a los clientes de esta aplicación."""

        if valor is not None and not valor.get_secret_value().startswith("sk_test_"):
            raise ValueError("STRIPE_API_KEY debe pertenecer a Stripe Sandbox.")
        return valor

    @field_validator("stripe_webhook_secret")
    @classmethod
    def validar_secreto_webhook(cls, valor: SecretStr | None) -> SecretStr | None:
        """Valida la forma del secreto firmado sin revelar su contenido."""

        if valor is not None and not valor.get_secret_value().startswith("whsec_"):
            raise ValueError("STRIPE_WEBHOOK_SECRET no tiene un formato válido.")
        return valor

    @field_validator("stripe_membership_price_ids")
    @classmethod
    def validar_price_ids(cls, valor: str) -> str:
        """Limita los planes configurados a tres Price IDs de Stripe."""

        ids = [item.strip() for item in valor.split(",") if item.strip()]
        if len(ids) > 3 or len(ids) != len(set(ids)):
            raise ValueError(
                "STRIPE_MEMBERSHIP_PRICE_IDS admite hasta tres IDs únicos."
            )
        if any(re.fullmatch(r"price_[A-Za-z0-9]+", item) is None for item in ids):
            raise ValueError("STRIPE_MEMBERSHIP_PRICE_IDS contiene un ID inválido.")
        return ",".join(ids)

    @property
    def stripe_price_ids(self) -> tuple[str, ...]:
        """Lista inmutable de Price IDs autorizados solo en el servidor."""

        if not self.stripe_membership_price_ids:
            return ()
        return tuple(self.stripe_membership_price_ids.split(","))

    @property
    def zona_horaria_estacionamiento(self) -> ZoneInfo:
        """Devuelve la zona validada que gobierna los horarios del estacionamiento."""

        return ZoneInfo(self.parking_timezone)

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

        if self.session_cookie_secure_override is not None:
            return self.session_cookie_secure_override
        return self.app_environment == "production"

    @property
    def customer_session_cookie_secure(self) -> bool:
        """Mantiene el atributo Secure separado para la cookie de clientes."""

        if self.customer_session_cookie_secure_override is not None:
            return self.customer_session_cookie_secure_override
        return self.app_environment == "production"


@lru_cache
def get_settings() -> Settings:
    # Pydantic completa los campos requeridos desde el entorno del proceso.
    return Settings()  # pyright: ignore[reportCallIssue]
