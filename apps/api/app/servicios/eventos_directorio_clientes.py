"""Eventos seguros para refrescar el directorio de clientes en tiempo real."""

from sqlalchemy.orm import Session

from app.models import EventoTiempoReal
from app.servicios.eventos_operadores import registrar_evento_tiempo_real


def registrar_evento_cliente_registrado(
    db: Session,
    *,
    cliente_id: int,
) -> EventoTiempoReal:
    """Notifica el alta; el SSE oculta el ID individual al serializar."""

    if type(cliente_id) is not int or cliente_id < 1:
        raise ValueError("El ID de cliente debe ser un entero positivo.")

    return registrar_evento_tiempo_real(
        db,
        recurso_tipo="cliente",
        recurso_id=cliente_id,
        tipo="cliente.registrado",
    )


def registrar_evento_membresia_actualizada(
    db: Session,
    *,
    cliente_id: int,
) -> EventoTiempoReal:
    """Notifica el cambio; el SSE no expone cliente ni datos de facturacion."""

    if type(cliente_id) is not int or cliente_id < 1:
        raise ValueError("El ID de cliente debe ser un entero positivo.")

    return registrar_evento_tiempo_real(
        db,
        recurso_tipo="cliente",
        recurso_id=cliente_id,
        tipo="membresia.actualizada",
    )


__all__ = [
    "registrar_evento_cliente_registrado",
    "registrar_evento_membresia_actualizada",
]
