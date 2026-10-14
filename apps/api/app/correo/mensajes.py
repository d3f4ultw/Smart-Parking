"""Construccion de correos de activacion y credenciales."""

from __future__ import annotations

import re
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from app.core.config import Settings, get_settings
from app.correo.errores import ConfiguracionSMTPInvalidaError
from app.models import RolUsuario, Usuario
from app.seguridad.correos import CorreoInvalidoError, normalizar_correo

ASUNTO_INVITACION_OPERADOR = "Activa tu cuenta de operador - Smart Parking"
ASUNTO_INVITACION_PROPIETARIO = "Verifica el registro OWNER - Smart Parking"
ASUNTO_DESVINCULACION_PROPIETARIO = "Confirma la desvinculación de tu cuenta OWNER"
ASUNTO_REGENERACION_CREDENCIALES_OPERADOR = "Contraseña regenerada - Smart Parking"


def construir_url_invitacion_operador(
    token: str,
    public_url: str | None = None,
) -> str:
    """Construye el enlace token-only de la pagina compartida de activacion."""

    base = (public_url or get_settings().app_public_url).strip()
    partes = urlsplit(base)
    if (
        partes.scheme not in {"http", "https"}
        or not partes.netloc
        or partes.query
        or partes.fragment
        or not token
    ):
        raise ConfiguracionSMTPInvalidaError

    path = f"{partes.path.rstrip('/')}/activar-cuenta"
    return urlunsplit(
        (
            partes.scheme,
            partes.netloc,
            path,
            urlencode({"token": token}),
            "",
        )
    )


def construir_url_invitacion_propietario(
    token: str,
    public_url: str | None = None,
) -> str:
    """Construye el enlace de primer registro OWNER con token opaco."""

    base = (public_url or get_settings().app_public_url).strip()
    partes = urlsplit(base)
    if (
        partes.scheme not in {"http", "https"}
        or not partes.netloc
        or partes.query
        or partes.fragment
        or not token
    ):
        raise ConfiguracionSMTPInvalidaError

    return urlunsplit(
        (
            partes.scheme,
            partes.netloc,
            f"{partes.path.rstrip('/')}/activar-propietario",
            urlencode({"token": token}),
            "",
        )
    )


def construir_url_confirmacion_desvinculacion(
    token: str,
    public_url: str | None = None,
) -> str:
    """Construye el enlace de confirmacion con el token solo en el fragmento."""

    base = (public_url or get_settings().app_public_url).strip()
    partes = urlsplit(base)
    if (
        partes.scheme not in {"http", "https"}
        or not partes.netloc
        or partes.query
        or partes.fragment
        or not re.fullmatch(r"[A-Za-z0-9_-]{43,64}", token)
    ):
        raise ConfiguracionSMTPInvalidaError

    return urlunsplit(
        (
            partes.scheme,
            partes.netloc,
            f"{partes.path.rstrip('/')}/confirmar-desvinculacion",
            "",
            f"desvincular={quote(token, safe='')}",
        )
    )


def _nombre_mostrable(usuario: Usuario) -> str:
    partes = [usuario.nombre, usuario.apellido_paterno, usuario.apellido_materno]
    return " ".join(parte.strip() for parte in partes if parte and parte.strip())


def _normalizar_remitente(from_email: str, settings: Settings) -> str:
    """Valida el remitente local de prueba sin flexibilizar correos de usuario."""

    permitir_entorno_pruebas = (
        settings.app_environment == "development"
        and settings.smtp_security.strip().casefold() == "none"
    )
    try:
        return normalizar_correo(
            from_email,
            permitir_entorno_pruebas=permitir_entorno_pruebas,
        )
    except CorreoInvalidoError as error:
        raise ConfiguracionSMTPInvalidaError from error


def construir_mensaje_invitacion_operador(
    usuario: Usuario,
    token: str,
    *,
    settings: Settings | None = None,
) -> EmailMessage:
    """Construye un correo de un solo enlace para OPERADOR."""

    valores = settings or get_settings()
    from_email = (valores.smtp_from_email or "").strip()
    from_name = valores.smtp_from_name.strip()
    if (
        not from_email
        or not from_name
        or any(caracter in from_name for caracter in "\r\n")
    ):
        raise ConfiguracionSMTPInvalidaError
    from_email = _normalizar_remitente(from_email, valores)
    if usuario.rol != RolUsuario.OPERADOR.value:
        raise ConfiguracionSMTPInvalidaError
    tipo_cuenta = "operador"
    asunto = ASUNTO_INVITACION_OPERADOR

    enlace = construir_url_invitacion_operador(token, valores.app_public_url)
    nombre = _nombre_mostrable(usuario) or tipo_cuenta
    horas = valores.activation_token_ttl_hours
    texto_horas = "1 hora" if horas == 1 else f"{horas} horas"
    texto = (
        "Smart Parking\n\n"
        f"Hola {nombre},\n\n"
        f"Se creó una cuenta de {tipo_cuenta} para ti.\n\n"
        "Activar mi cuenta:\n"
        f"{enlace}\n\n"
        "Al activar tu cuenta podrás crear tu contraseña.\n"
        f"Esta invitación vence en {texto_horas}.\n"
        "Si no esperabas esta cuenta, ignora este correo o comunícate con "
        "el administrador.\n"
    )
    html = (
        "<!doctype html><html><body>"
        "<p>Smart Parking</p>"
        f"<p>Hola {escape(nombre)},</p>"
        f"<p>Se creó una cuenta de {escape(tipo_cuenta)} para ti.</p>"
        f'<p><a href="{escape(enlace, quote=True)}">Activar mi cuenta</a></p>'
        "<p>Al activar tu cuenta podrás crear tu contraseña.</p>"
        f"<p>Esta invitación vence en {escape(texto_horas)}.</p>"
        "<p>Si no esperabas esta cuenta, ignora este correo o comunícate con "
        "el administrador.</p>"
        "</body></html>"
    )
    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = formataddr((from_name, from_email))
    mensaje["To"] = usuario.correo
    mensaje.set_content(texto)
    mensaje.add_alternative(html, subtype="html")
    return mensaje


def construir_mensaje_invitacion_propietario(
    correo: str,
    token: str,
    *,
    settings: Settings | None = None,
) -> EmailMessage:
    """Construye el correo con vigencia del enlace y desafio de registro."""

    valores = settings or get_settings()
    from_email = (valores.smtp_from_email or "").strip()
    from_name = valores.smtp_from_name.strip()
    if (
        not from_email
        or not from_name
        or any(caracter in from_name for caracter in "\r\n")
    ):
        raise ConfiguracionSMTPInvalidaError
    from_email = _normalizar_remitente(from_email, valores)
    enlace = construir_url_invitacion_propietario(token, valores.app_public_url)
    texto = (
        "Smart Parking\n\n"
        "Se solicitó verificar este correo para registrar el primer OWNER.\n\n"
        "Verifica el correo y continúa el registro desde este enlace:\n"
        f"{enlace}\n\n"
        "El enlace tiene una vigencia máxima de 15 minutos desde este envío. "
        "Puedes volver a abrirlo cuantas veces necesites mientras siga vigente; "
        "Abrirlo no reinicia el tiempo.\n"
        "La solicitud vence 60 minutos después del primer envío. Durante esa "
        "hora se permiten hasta 3 reenvíos, con 5 minutos entre envíos.\n"
        "Completa el registro antes de que venza el enlace.\n"
        "Si no solicitaste este registro, ignora este mensaje.\n"
    )
    html = (
        "<!doctype html><html><body>"
        "<p>Smart Parking</p>"
        "<p>Se solicitó verificar este correo para registrar el primer OWNER.</p>"
        f'<p><a href="{escape(enlace, quote=True)}">'
        "Verificar correo y continuar</a></p>"
        "<p>El enlace tiene una vigencia máxima de 15 minutos desde este envío. "
        "Puedes volver a abrirlo cuantas veces necesites mientras siga vigente; "
        "Abrirlo no reinicia el tiempo.</p>"
        "<p>La solicitud vence 60 minutos después del primer envío. Durante "
        "esa hora se permiten hasta 3 reenvíos, con 5 minutos entre envíos.</p>"
        "<p>Completa el registro antes de que venza el enlace.</p>"
        "<p>Si no solicitaste este registro, ignora este mensaje.</p>"
        "</body></html>"
    )
    mensaje = EmailMessage()
    mensaje["Subject"] = ASUNTO_INVITACION_PROPIETARIO
    mensaje["From"] = formataddr((from_name, from_email))
    mensaje["To"] = correo
    mensaje.set_content(texto)
    mensaje.add_alternative(html, subtype="html")
    return mensaje


def construir_mensaje_confirmacion_desvinculacion_propietario(
    correo: str,
    token: str,
    *,
    settings: Settings | None = None,
) -> EmailMessage:
    """Construye el correo de confirmacion automatica de desvinculacion."""

    valores = settings or get_settings()
    from_email = (valores.smtp_from_email or "").strip()
    from_name = valores.smtp_from_name.strip()
    if (
        not from_email
        or not from_name
        or any(caracter in from_name for caracter in "\r\n")
    ):
        raise ConfiguracionSMTPInvalidaError
    from_email = _normalizar_remitente(from_email, valores)
    enlace = construir_url_confirmacion_desvinculacion(
        token,
        valores.app_public_url,
    )
    texto = (
        "Smart Parking\n\n"
        "Se solicitó desvincular esta cuenta de OWNER.\n\n"
        "Abre este enlace para completar la desvinculación automáticamente. "
        "El enlace vence en 15 minutos y solo puede usarse una vez:\n"
        f"{enlace}\n\n"
        "La cuenta y su historial se conservarán, pero perderá el acceso "
        "operativo asignado.\n"
        "Si no solicitaste esta acción, ignora este mensaje.\n"
    )
    html = (
        "<!doctype html><html><body>"
        "<p>Smart Parking</p>"
        "<p>Se solicitó desvincular esta cuenta de OWNER.</p>"
        f'<p><a href="{escape(enlace, quote=True)}">'
        "Completar desvinculación</a></p>"
        "<p>El enlace vence en 15 minutos y solo puede usarse una vez. "
        "Al abrirlo, la desvinculación se completará automáticamente.</p>"
        "<p>La cuenta y su historial se conservarán, pero perderá el acceso "
        "operativo asignado.</p>"
        "<p>Si no solicitaste esta acción, ignora este mensaje.</p>"
        "</body></html>"
    )
    mensaje = EmailMessage()
    mensaje["Subject"] = ASUNTO_DESVINCULACION_PROPIETARIO
    mensaje["From"] = formataddr((from_name, from_email))
    mensaje["To"] = correo
    mensaje.set_content(texto)
    mensaje.add_alternative(html, subtype="html")
    return mensaje


def construir_mensaje_regeneracion_credenciales_operador(
    usuario: Usuario,
    contrasena: str,
    *,
    settings: Settings | None = None,
) -> EmailMessage:
    """Construye el correo que entrega una contraseña regenerada."""

    return _construir_mensaje_credenciales_operador(
        usuario,
        contrasena,
        asunto=ASUNTO_REGENERACION_CREDENCIALES_OPERADOR,
        motivo="Se regeneró la contraseña de tu cuenta de OPERADOR de Smart Parking.",
        settings=settings,
    )


def _construir_mensaje_credenciales_operador(
    usuario: Usuario,
    contrasena: str,
    *,
    asunto: str,
    motivo: str,
    settings: Settings | None,
) -> EmailMessage:
    """Construye MIME de acceso sin exponer datos fuera del correo."""

    valores = settings or get_settings()
    from_email = (valores.smtp_from_email or "").strip()
    from_name = valores.smtp_from_name.strip()
    if (
        not from_email
        or not from_name
        or any(caracter in from_name for caracter in "\r\n")
    ):
        raise ConfiguracionSMTPInvalidaError
    from_email = _normalizar_remitente(from_email, valores)

    nombre = _nombre_mostrable(usuario) or "operador"
    texto = (
        f"Hola {nombre},\n\n"
        f"{motivo}\n\n"
        f"Correo: {usuario.correo}\n"
        f"Contrasena: {contrasena}\n\n"
        "Usa estas credenciales para iniciar sesion.\n"
    )
    html = (
        "<!doctype html><html><body>"
        f"<p>Hola {escape(nombre)},</p>"
        f"<p>{escape(motivo)}</p>"
        f"<p><strong>Correo:</strong> {escape(usuario.correo)}</p>"
        f"<p><strong>Contrasena:</strong> <code>{escape(contrasena)}</code></p>"
        "<p>Usa estas credenciales para iniciar sesion.</p>"
        "</body></html>"
    )

    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = formataddr((from_name, from_email))
    mensaje["To"] = usuario.correo
    mensaje.set_content(texto)
    mensaje.add_alternative(html, subtype="html")
    return mensaje


__all__ = [
    "ASUNTO_INVITACION_OPERADOR",
    "ASUNTO_INVITACION_PROPIETARIO",
    "ASUNTO_DESVINCULACION_PROPIETARIO",
    "ASUNTO_REGENERACION_CREDENCIALES_OPERADOR",
    "construir_mensaje_invitacion_propietario",
    "construir_mensaje_confirmacion_desvinculacion_propietario",
    "construir_url_confirmacion_desvinculacion",
    "construir_mensaje_invitacion_operador",
    "construir_mensaje_regeneracion_credenciales_operador",
    "construir_url_invitacion_propietario",
    "construir_url_invitacion_operador",
]
