"""Seleccion de transportes de correo segun la configuracion."""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.correo.smtp import SMTPTransport, TransporteCorreo


def crear_transporte_correo(
    settings: Settings | None = None,
) -> TransporteCorreo:
    """Crea el unico transporte de entrega permitido por la configuracion."""

    valores = settings or get_settings()
    return SMTPTransport(valores)


__all__ = ["crear_transporte_correo"]
