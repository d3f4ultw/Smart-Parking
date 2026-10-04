"""Transporte SMTP seguro y agnostico del proveedor."""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from math import isfinite
from typing import Protocol

from app.core.config import Settings, get_settings
from app.correo.errores import (
    ConfiguracionSMTPInvalidaError,
    ErrorCorreo,
    ErrorEnvioCorreo,
)
from app.correo.mensajes import (
    DatosActivacionCorreo,
    construir_mensaje_activacion,
)
from app.seguridad.correos import CorreoInvalidoError, normalizar_correo


class TransporteCorreo(Protocol):
    """Seam minimo que permite seleccionar otro transporte en pruebas."""

    def enviar(self, datos: DatosActivacionCorreo | EmailMessage) -> None:
        """Entrega activaciones o mensajes MIME ya construidos."""


@dataclass(frozen=True, slots=True)
class ConfiguracionSMTP:
    """Configuracion validada sin incluirla en mensajes de error publicos."""

    host: str
    port: int
    username: str
    password: str = field(repr=False)
    from_email: str
    from_name: str
    security: str
    timeout_seconds: float


def cargar_configuracion_smtp(settings: Settings | None = None) -> ConfiguracionSMTP:
    """Valida SMTP sin incluir valores de configuracion en los errores."""

    valores = settings or get_settings()
    host = (valores.smtp_host or "").strip()
    username = (valores.smtp_username or "").strip()
    password = (
        valores.smtp_password.get_secret_value()
        if valores.smtp_password is not None
        else ""
    )
    from_email = (valores.smtp_from_email or "").strip()
    from_name = valores.smtp_from_name.strip() or "Smart Parking"

    requeridos = (("SMTP_HOST", host), ("SMTP_FROM_EMAIL", from_email))
    for campo, valor in requeridos:
        if not valor:
            raise ConfiguracionSMTPInvalidaError(campo)

    try:
        port = int(valores.smtp_port or "")
    except TypeError, ValueError:
        raise ConfiguracionSMTPInvalidaError("SMTP_PORT") from None

    try:
        timeout_seconds = float(valores.smtp_timeout_seconds or "")
    except TypeError, ValueError:
        raise ConfiguracionSMTPInvalidaError("SMTP_TIMEOUT_SECONDS") from None

    security = valores.smtp_security.strip().casefold()
    if security not in {"ssl", "starttls", "none"}:
        raise ConfiguracionSMTPInvalidaError("SMTP_SECURITY")
    if security == "none":
        if valores.app_environment != "development":
            raise ConfiguracionSMTPInvalidaError("SMTP_SECURITY")
        if username:
            raise ConfiguracionSMTPInvalidaError("SMTP_USERNAME")
        if password:
            raise ConfiguracionSMTPInvalidaError("SMTP_PASSWORD")
    else:
        if not username:
            raise ConfiguracionSMTPInvalidaError("SMTP_USERNAME")
        if not password:
            raise ConfiguracionSMTPInvalidaError("SMTP_PASSWORD")

    try:
        from_email = normalizar_correo(
            from_email,
            permitir_entorno_pruebas=(
                valores.app_environment == "development" and security == "none"
            ),
        )
    except CorreoInvalidoError:
        raise ConfiguracionSMTPInvalidaError("SMTP_FROM_EMAIL") from None

    if not 1 <= port <= 65_535:
        raise ConfiguracionSMTPInvalidaError("SMTP_PORT")
    if not isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ConfiguracionSMTPInvalidaError("SMTP_TIMEOUT_SECONDS")

    return ConfiguracionSMTP(
        host=host,
        port=port,
        username=username,
        password=password,
        from_email=from_email,
        from_name=from_name,
        security=security,
        timeout_seconds=timeout_seconds,
    )


class SMTPTransport:
    """Entrega mensajes con la politica SMTP validada para cada ambiente."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    def enviar(self, datos: DatosActivacionCorreo | EmailMessage) -> None:
        mensaje = (
            datos
            if isinstance(datos, EmailMessage)
            else construir_mensaje_activacion(datos, settings=self._settings)
        )
        configuracion = cargar_configuracion_smtp(self._settings)
        contexto = ssl.create_default_context()

        try:
            if configuracion.security == "ssl":
                with smtplib.SMTP_SSL(
                    configuracion.host,
                    configuracion.port,
                    timeout=configuracion.timeout_seconds,
                    context=contexto,
                ) as smtp:
                    smtp.login(configuracion.username, configuracion.password)
                    rechazados = smtp.send_message(mensaje)
            elif configuracion.security == "starttls":
                with smtplib.SMTP(
                    configuracion.host,
                    configuracion.port,
                    timeout=configuracion.timeout_seconds,
                ) as smtp:
                    smtp.ehlo()
                    smtp.starttls(context=contexto)
                    smtp.ehlo()
                    smtp.login(configuracion.username, configuracion.password)
                    rechazados = smtp.send_message(mensaje)
            else:
                with smtplib.SMTP(
                    configuracion.host,
                    configuracion.port,
                    timeout=configuracion.timeout_seconds,
                ) as smtp:
                    rechazados = smtp.send_message(mensaje)
            if rechazados:
                raise ErrorEnvioCorreo from None
        except (OSError, TimeoutError, smtplib.SMTPException, ssl.SSLError) as error:
            raise ErrorEnvioCorreo from error


__all__ = [
    "ConfiguracionSMTP",
    "ConfiguracionSMTPInvalidaError",
    "ErrorCorreo",
    "ErrorEnvioCorreo",
    "SMTPTransport",
    "TransporteCorreo",
    "cargar_configuracion_smtp",
]
