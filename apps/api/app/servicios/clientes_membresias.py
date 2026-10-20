"""Consultas de solo lectura con respuesta separada de datos privados."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.models import Cliente, Membresia
from app.servicios.stripe_membresias import mapear_estado_membresia

TAMANO_PAGINA_CLIENTES = 10
_FORMATO_CODIGO_CLIENTE = re.compile(r"CLI-([0-9]{4,})\Z")


@dataclass(frozen=True, slots=True)
class ClienteResumenDTO:
    codigo_cliente: str
    nombre_completo: str
    estado_membresia: str


@dataclass(frozen=True, slots=True)
class PaginaClientesDTO:
    clientes: tuple[ClienteResumenDTO, ...]
    pagina: int
    tamano_pagina: int
    total: int
    total_paginas: int


@dataclass(frozen=True, slots=True)
class DetalleMembresiaDTO:
    codigo_cliente: str
    plan: str
    monto_centavos: int
    moneda: str
    fecha_inicio: datetime | None
    proxima_renovacion: datetime | None
    estado: str
    cancelacion_programada: bool


class ClienteNoEncontradoError(LookupError):
    """El codigo publico no pertenece a un cliente existente."""


def formatear_codigo_cliente(cliente_id: int) -> str:
    """Deriva el codigo visible desde la identidad PostgreSQL sin duplicarla."""

    return f"CLI-{cliente_id:04d}"


def _obtener_id_codigo(codigo_cliente: str) -> int:
    coincidencia = _FORMATO_CODIGO_CLIENTE.fullmatch(codigo_cliente)
    if coincidencia is None:
        raise ClienteNoEncontradoError
    cliente_id = int(coincidencia.group(1))
    if cliente_id < 1 or formatear_codigo_cliente(cliente_id) != codigo_cliente:
        raise ClienteNoEncontradoError
    return cliente_id


def _orden_membresia_actual():
    """Prioriza una suscripcion vigente sobre el historial cancelado."""

    return case(
        (
            Membresia.estado_stripe.in_(
                ("active", "past_due", "unpaid", "paused", "trialing")
            ),
            0,
        ),
        else_=1,
    )


def listar_clientes(db: Session, *, pagina: int) -> PaginaClientesDTO:
    """Lista por paginas, conservando el correo fuera de los DTO publicos."""

    if type(pagina) is not int or pagina < 1:
        raise ValueError("La pagina debe ser un entero positivo.")
    db.rollback()
    with db.begin():
        total = int(db.scalar(select(func.count()).select_from(Cliente)) or 0)
        filas = list(
            db.scalars(
                select(Cliente)
                .order_by(desc(Cliente.id))
                .offset((pagina - 1) * TAMANO_PAGINA_CLIENTES)
                .limit(TAMANO_PAGINA_CLIENTES)
            ).all()
        )
        membresias: dict[int, Membresia] = {}
        if filas:
            recientes = db.scalars(
                select(Membresia)
                .where(Membresia.cliente_id.in_([cliente.id for cliente in filas]))
                .order_by(
                    _orden_membresia_actual(),
                    desc(Membresia.creada_en),
                    desc(Membresia.id),
                )
            ).all()
            for membresia in recientes:
                membresias.setdefault(membresia.cliente_id, membresia)
        clientes = tuple(
            ClienteResumenDTO(
                codigo_cliente=formatear_codigo_cliente(cliente.id),
                nombre_completo=cliente.nombre_completo or "Cliente sin nombre",
                estado_membresia=(
                    mapear_estado_membresia(
                        membresias[cliente.id].estado_stripe,
                        membresias[cliente.id].cancelacion_programada,
                    )
                    if cliente.id in membresias
                    else "pendiente"
                ),
            )
            for cliente in filas
        )
    return PaginaClientesDTO(
        clientes=clientes,
        pagina=pagina,
        tamano_pagina=TAMANO_PAGINA_CLIENTES,
        total=total,
        total_paginas=(total + TAMANO_PAGINA_CLIENTES - 1) // TAMANO_PAGINA_CLIENTES,
    )


def obtener_detalle_membresia(
    db: Session,
    *,
    codigo_cliente: str,
) -> DetalleMembresiaDTO:
    """Devuelve solo los campos de modal; omite correo e IDs externos."""

    cliente_id = _obtener_id_codigo(codigo_cliente)
    cliente = db.get(Cliente, cliente_id)
    if cliente is None:
        raise ClienteNoEncontradoError
    membresia = db.scalar(
        select(Membresia)
        .where(Membresia.cliente_id == cliente_id)
        .order_by(
            _orden_membresia_actual(),
            desc(Membresia.creada_en),
            desc(Membresia.id),
        )
        .limit(1)
    )
    if membresia is None:
        raise ClienteNoEncontradoError
    return DetalleMembresiaDTO(
        codigo_cliente=codigo_cliente,
        plan=membresia.nombre_plan,
        monto_centavos=membresia.monto_centavos,
        moneda=membresia.moneda,
        fecha_inicio=membresia.fecha_inicio,
        proxima_renovacion=membresia.periodo_actual_fin,
        estado=mapear_estado_membresia(
            membresia.estado_stripe,
            membresia.cancelacion_programada,
        ),
        cancelacion_programada=membresia.cancelacion_programada,
    )


__all__ = [
    "ClienteNoEncontradoError",
    "DetalleMembresiaDTO",
    "PaginaClientesDTO",
    "TAMANO_PAGINA_CLIENTES",
    "formatear_codigo_cliente",
    "listar_clientes",
    "obtener_detalle_membresia",
]
