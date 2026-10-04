"""Construccion de correos de activacion y credenciales."""

from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
from urllib.parse import urlencode, urlsplit, urlunsplit

from app.core.config import Settings, get_settings
from app.correo.errores import ConfiguracionSMTPInvalidaError
from app.models import RolUsuario, Usuario
from app.seguridad.correos import CorreoInvalidoError, normalizar_correo
from app.servicios.activaciones import (
    MINUTOS_VIGENCIA_ACTIVACION,
    ModoActivacion,
    ResultadoActivacion,
    ResultadoReenvioActivacion,
)

ASUNTO_ACTIVACION = "Activa tu cuenta de administrador - Smart Parking"
ASUNTO_INVITACION_ADMIN = "Activa tu cuenta de administrador - Smart Parking"
ASUNTO_INVITACION_OPERADOR = "Activa tu cuenta de operador - Smart Parking"
ASUNTO_REGENERACION_CREDENCIALES_OPERADOR = "Contraseña regenerada - Smart Parking"


@dataclass(frozen=True, slots=True)
class DatosActivacionCorreo:
    """Datos efimeros compartidos por cualquier transporte de activacion."""

    correo: str
    nombre: str
    enlace: str = field(repr=False)
    codigo: str = field(repr=False)
    expira_en_minutos: int = MINUTOS_VIGENCIA_ACTIVACION
    contrasena_temporal: str | None = field(default=None, repr=False)
    es_reenvio: bool = False

    @property
    def modo(self) -> ModoActivacion:
        """Devuelve el modo que debe usar la pagina de activacion."""

        return "temporal" if self.contrasena_temporal is not None else "manual"


def construir_url_activacion(
    token: str,
    public_url: str | None = None,
) -> str:
    """Construye el enlace publico usando solamente el token opaco."""

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

    path = f"{partes.path.rstrip('/')}/activar"
    return urlunsplit(
        (
            partes.scheme,
            partes.netloc,
            path,
            urlencode({"token": token}),
            "",
        )
    )


def construir_url_invitacion_operador(
    token: str,
    public_url: str | None = None,
) -> str:
    """Construye el enlace de invitacion OPERADOR sin datos de cuenta."""

    return construir_url_invitacion_cuenta(token, public_url)


def construir_url_invitacion_cuenta(
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


def construir_datos_activacion(
    usuario: Usuario,
    resultado: ResultadoActivacion | ResultadoReenvioActivacion,
    contrasena_temporal: str | None,
    *,
    settings: Settings | None = None,
    es_reenvio: bool = False,
) -> DatosActivacionCorreo:
    """Prepara los datos efimeros que consumen los transportes de correo."""

    valores = settings or get_settings()
    enlace = construir_url_activacion(
        resultado.token,
        valores.app_public_url,
    )
    return DatosActivacionCorreo(
        correo=usuario.correo,
        nombre=_nombre_mostrable(usuario) or "administrador",
        enlace=enlace,
        codigo=resultado.codigo,
        contrasena_temporal=contrasena_temporal,
        es_reenvio=es_reenvio,
    )


def construir_mensaje_activacion(
    datos_o_usuario: DatosActivacionCorreo | Usuario,
    resultado: ResultadoActivacion | ResultadoReenvioActivacion | None = None,
    contrasena_temporal: str | None = None,
    *,
    settings: Settings | None = None,
) -> EmailMessage:
    """Construye el MIME desde datos de entrega o desde la API historica."""

    if isinstance(datos_o_usuario, DatosActivacionCorreo):
        if resultado is not None or contrasena_temporal is not None:
            raise TypeError("Los datos de activacion no aceptan argumentos extra.")
        datos = datos_o_usuario
    else:
        if resultado is None:
            raise TypeError("Falta el resultado de activacion.")
        datos = construir_datos_activacion(
            datos_o_usuario,
            resultado,
            contrasena_temporal,
            settings=settings,
        )

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

    if datos.contrasena_temporal is None:
        password_text = ""
        password_html = ""
    else:
        password_text = (
            "\nContrasena temporal: "
            f"{datos.contrasena_temporal}\n"
            "Debes reemplazar esta contrasena durante la activacion.\n"
        )
        password_html = (
            "<p><strong>Contrasena temporal:</strong> "
            f"{escape(datos.contrasena_temporal)}<br>"
            "Debes reemplazar esta contrasena durante la activacion.</p>"
        )

    texto = (
        f"Hola {datos.nombre},\n\n"
        "Activa tu cuenta de administrador de Smart Parking.\n\n"
        "Enlace de activacion:\n"
        f"{datos.enlace}\n\n"
        f"Codigo de verificacion: {datos.codigo}\n"
        f"Este codigo y enlace expiran en {datos.expira_en_minutos} minutos.\n"
        f"{password_text}"
    )
    nombre_html = escape(datos.nombre)
    url_html = escape(datos.enlace, quote=True)
    codigo_html = escape(datos.codigo)
    html = (
        "<!doctype html><html><body>"
        f"<p>Hola {nombre_html},</p>"
        "<p>Activa tu cuenta de administrador de Smart Parking.</p>"
        f'<p><a href="{url_html}">Activar cuenta</a></p>'
        f"<p><strong>Codigo de verificacion:</strong> "
        f"<code>{codigo_html}</code><br>"
        f"Este codigo y enlace expiran en {datos.expira_en_minutos} minutos.</p>"
        f"{password_html}"
        "</body></html>"
    )

    mensaje = EmailMessage()
    mensaje["Subject"] = ASUNTO_ACTIVACION
    mensaje["From"] = formataddr((from_name, from_email))
    mensaje["To"] = datos.correo
    mensaje.set_content(texto)
    mensaje.add_alternative(html, subtype="html")
    return mensaje


def construir_mensaje_invitacion_operador(
    usuario: Usuario,
    token: str,
    *,
    settings: Settings | None = None,
) -> EmailMessage:
    """Construye el correo de activacion token-only para OPERADOR."""

    return construir_mensaje_invitacion_cuenta(usuario, token, settings=settings)


def construir_mensaje_invitacion_cuenta(
    usuario: Usuario,
    token: str,
    *,
    settings: Settings | None = None,
) -> EmailMessage:
    """Construye un correo de un solo enlace para ADMIN u OPERADOR."""

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

    if usuario.rol == RolUsuario.ADMIN.value:
        tipo_cuenta = "administrador"
        asunto = ASUNTO_INVITACION_ADMIN
    elif usuario.rol == RolUsuario.OPERADOR.value:
        tipo_cuenta = "operador"
        asunto = ASUNTO_INVITACION_OPERADOR
    else:
        raise ConfiguracionSMTPInvalidaError

    enlace = construir_url_invitacion_cuenta(token, valores.app_public_url)
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
    "ASUNTO_ACTIVACION",
    "ASUNTO_INVITACION_ADMIN",
    "ASUNTO_INVITACION_OPERADOR",
    "ASUNTO_REGENERACION_CREDENCIALES_OPERADOR",
    "DatosActivacionCorreo",
    "construir_mensaje_invitacion_cuenta",
    "construir_mensaje_invitacion_operador",
    "construir_mensaje_regeneracion_credenciales_operador",
    "construir_mensaje_activacion",
    "construir_datos_activacion",
    "construir_url_activacion",
    "construir_url_invitacion_cuenta",
    "construir_url_invitacion_operador",
]
