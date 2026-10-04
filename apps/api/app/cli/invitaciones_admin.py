"""Entrega controlada de invitaciones token-only desde los CLI ADMIN."""

from __future__ import annotations

from collections.abc import Callable
from email.message import EmailMessage

from app.core.config import Settings
from app.correo.mensajes import construir_mensaje_invitacion_cuenta
from app.correo.smtp import TransporteCorreo
from app.correo.transportes import crear_transporte_correo
from app.models import Usuario


def entregar_invitacion_admin(
    usuario: Usuario,
    token: str,
    *,
    settings: Settings,
    transporte: TransporteCorreo | None = None,
) -> None:
    """Entrega el enlace token-only usando el transporte SMTP configurado."""

    mensaje: EmailMessage = construir_mensaje_invitacion_cuenta(
        usuario,
        token,
        settings=settings,
    )
    (transporte or crear_transporte_correo(settings)).enviar(mensaje)


def crear_callback_entrega_admin(
    *,
    settings: Settings,
    transporte: TransporteCorreo | None = None,
) -> Callable[[Usuario, str], None]:
    """Adapta la entrega al callback transaccional del servicio de usuarios."""

    def entregar(usuario: Usuario, token: str) -> None:
        entregar_invitacion_admin(
            usuario,
            token,
            settings=settings,
            transporte=transporte,
        )

    return entregar


__all__ = [
    "crear_callback_entrega_admin",
    "entregar_invitacion_admin",
]
