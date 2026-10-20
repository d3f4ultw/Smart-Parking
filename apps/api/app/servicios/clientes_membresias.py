"""Consultas y controles de checkout para cuentas de cliente autenticadas."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, case, desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    Cliente,
    CuentaCliente,
    IntentoCheckoutCliente,
    Membresia,
)
from app.servicios.stripe_membresias import mapear_estado_membresia

TAMANO_PAGINA_CLIENTES = 10
_FORMATO_CODIGO_CLIENTE = re.compile(r"CLI-([0-9]{4,})\Z")
_ESTADOS_INTENTO_ACTIVOS = ("creado", "abierto")
_ESTADOS_MEMBRESIA_VIGENTE = (
    "incomplete",
    "active",
    "past_due",
    "unpaid",
    "paused",
    "trialing",
)
_DURACION_CHECKOUT = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class ClienteResumenDTO:
    codigo_cliente: str | None
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


@dataclass(frozen=True, slots=True)
class DetalleMembresiaCuentaDTO:
    plan: str
    monto_centavos: int
    moneda: str
    intervalo: str
    intervalo_cantidad: int
    fecha_inicio: datetime | None
    periodo_actual_inicio: datetime | None
    periodo_actual_fin: datetime | None
    cancelacion_programada: bool


@dataclass(frozen=True, slots=True)
class MembresiaCuentaDTO:
    estado: str
    membresia: DetalleMembresiaCuentaDTO | None
    checkout_pendiente: bool
    puede_comprar: bool


@dataclass(frozen=True, slots=True)
class IntentoCheckoutDTO:
    id: UUID
    cuenta_cliente_id: int
    correo: str
    clave_solicitud: UUID
    stripe_idempotency_key: str
    checkout_session_id: str | None
    stripe_customer_id: str | None
    expira_en: datetime


class ClienteNoEncontradoError(LookupError):
    """El codigo publico no pertenece a un cliente existente."""


class IntentoCheckoutEnCursoError(RuntimeError):
    """La cuenta ya tiene otra solicitud de Checkout en curso."""


class MembresiaVigenteError(RuntimeError):
    """La cuenta ya tiene una membresia vigente o en recuperacion de pago."""


class IntentoCheckoutNoDisponibleError(RuntimeError):
    """La cuenta o el intento ya no permiten iniciar un Checkout."""


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
            Membresia.estado_stripe.in_(_ESTADOS_MEMBRESIA_VIGENTE),
            0,
        ),
        else_=1,
    )


def _subconsulta_membresias_actuales():
    orden = (
        case((Membresia.estado_stripe.in_(_ESTADOS_MEMBRESIA_VIGENTE), 0), else_=1),
        desc(Membresia.creada_en),
        desc(Membresia.id),
    )
    return (
        select(
            Membresia.cliente_id.label("cliente_id"),
            Membresia.estado_stripe.label("estado_stripe"),
            Membresia.cancelacion_programada.label("cancelacion_programada"),
            func.row_number()
            .over(partition_by=Membresia.cliente_id, order_by=orden)
            .label("posicion"),
        )
        .subquery()
    )


def _categoria_membresia(estado_stripe):
    return case(
        (estado_stripe.in_(("active", "trialing")), "activa"),
        (estado_stripe == "canceled", "cancelada"),
        else_="sin_membresia",
    )


def _nombre_cuenta(cuenta: CuentaCliente) -> str:
    return " ".join(
        parte
        for parte in (
            cuenta.nombre,
            cuenta.apellido_paterno,
            cuenta.apellido_materno,
        )
        if parte
    )


def _nombre_resumen(
    cuenta: CuentaCliente | None,
    cliente_nombre: str | None,
) -> str:
    if cuenta is None:
        return cliente_nombre or "Cliente sin nombre"
    return _nombre_cuenta(cuenta) or cliente_nombre or "Cliente sin nombre"


def listar_clientes(
    db: Session,
    *,
    pagina: int,
    estado: str | None = None,
) -> PaginaClientesDTO:
    """Lista el directorio de cuentas con una categoria filtrada en PostgreSQL."""

    if type(pagina) is not int or pagina < 1:
        raise ValueError("La pagina debe ser un entero positivo.")
    if estado not in {None, "sin_membresia", "activa", "cancelada"}:
        raise ValueError("La categoria de membresia no es valida.")

    membresias = _subconsulta_membresias_actuales()
    consulta = (
        select(
            CuentaCliente,
            Cliente.id.label("cliente_id"),
            Cliente.nombre_completo.label("cliente_nombre"),
            membresias.c.estado_stripe,
            membresias.c.cancelacion_programada,
        )
        .outerjoin(
            Cliente,
            Cliente.cuenta_cliente_id == CuentaCliente.id,
            full=True,
        )
        .outerjoin(
            membresias,
            and_(membresias.c.cliente_id == Cliente.id, membresias.c.posicion == 1),
        )
    )
    if estado is not None:
        categoria = _categoria_membresia(membresias.c.estado_stripe)
        consulta = consulta.where(categoria == estado)

    db.rollback()
    with db.begin():
        total = int(
            db.scalar(
                select(func.count()).select_from(consulta.order_by(None).subquery())
            )
            or 0
        )
        filas = db.execute(
            consulta.order_by(desc(CuentaCliente.id))
            .offset((pagina - 1) * TAMANO_PAGINA_CLIENTES)
            .limit(TAMANO_PAGINA_CLIENTES)
        ).all()
        clientes = tuple(
            ClienteResumenDTO(
                codigo_cliente=(
                    formatear_codigo_cliente(cliente_id)
                    if cliente_id is not None
                    else None
                ),
                nombre_completo=_nombre_resumen(cuenta, cliente_nombre),
                estado_membresia=(
                    mapear_estado_membresia(estado_stripe, cancelacion_programada)
                    if estado_stripe is not None
                    else "pendiente"
                ),
            )
            for (
                cuenta,
                cliente_id,
                cliente_nombre,
                estado_stripe,
                cancelacion_programada,
            ) in filas
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
    """Devuelve solo los campos del modal; omite correo e IDs externos."""

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


def obtener_membresia_cuenta(
    db: Session,
    *,
    cuenta_cliente_id: int,
) -> MembresiaCuentaDTO:
    """Consulta el estado privado que pertenece a la cuenta autenticada."""

    ahora = datetime.now(UTC)
    checkout_pendiente = (
        db.scalar(
            select(IntentoCheckoutCliente.id)
            .where(
                IntentoCheckoutCliente.cuenta_cliente_id == cuenta_cliente_id,
                IntentoCheckoutCliente.estado.in_(_ESTADOS_INTENTO_ACTIVOS),
                IntentoCheckoutCliente.expira_en > ahora,
            )
            .limit(1)
        )
        is not None
    )
    cliente = db.scalar(
        select(Cliente).where(Cliente.cuenta_cliente_id == cuenta_cliente_id)
    )
    if cliente is None:
        return MembresiaCuentaDTO(
            estado="sin_membresia",
            membresia=None,
            checkout_pendiente=checkout_pendiente,
            puede_comprar=not checkout_pendiente,
        )
    membresia = db.scalar(
        select(Membresia)
        .where(Membresia.cliente_id == cliente.id)
        .order_by(
            _orden_membresia_actual(),
            desc(Membresia.creada_en),
            desc(Membresia.id),
        )
        .limit(1)
    )
    if membresia is None:
        return MembresiaCuentaDTO(
            estado="sin_membresia",
            membresia=None,
            checkout_pendiente=checkout_pendiente,
            puede_comprar=not checkout_pendiente,
        )
    membresia_bloquea_compra = membresia.estado_stripe in _ESTADOS_MEMBRESIA_VIGENTE
    return MembresiaCuentaDTO(
        estado=mapear_estado_membresia(
            membresia.estado_stripe,
            membresia.cancelacion_programada,
        ),
        membresia=DetalleMembresiaCuentaDTO(
            plan=membresia.nombre_plan,
            monto_centavos=membresia.monto_centavos,
            moneda=membresia.moneda,
            intervalo=membresia.intervalo,
            intervalo_cantidad=membresia.intervalo_cantidad,
            fecha_inicio=membresia.fecha_inicio,
            periodo_actual_inicio=membresia.periodo_actual_inicio,
            periodo_actual_fin=membresia.periodo_actual_fin,
            cancelacion_programada=membresia.cancelacion_programada,
        ),
        checkout_pendiente=checkout_pendiente,
        puede_comprar=not checkout_pendiente and not membresia_bloquea_compra,
    )


def crear_o_reusar_intento_checkout(
    db: Session,
    *,
    cuenta_cliente_id: int,
    clave_solicitud: UUID,
) -> IntentoCheckoutDTO:
    """Persiste una solicitud antes de llamar a Stripe y serializa por cuenta."""

    db.rollback()
    ahora = datetime.now(UTC)
    intento_solicitud_no_disponible = False
    resultado: IntentoCheckoutDTO | None = None
    with db.begin():
        cuenta = db.scalar(
            select(CuentaCliente)
            .where(CuentaCliente.id == cuenta_cliente_id)
            .with_for_update()
        )
        if cuenta is None or not cuenta.esta_activa:
            raise IntentoCheckoutNoDisponibleError

        intento_existente = db.scalar(
            select(IntentoCheckoutCliente)
            .where(
                IntentoCheckoutCliente.cuenta_cliente_id == cuenta.id,
                IntentoCheckoutCliente.clave_solicitud == clave_solicitud,
            )
            .with_for_update()
        )
        if intento_existente is not None:
            if (
                intento_existente.estado in _ESTADOS_INTENTO_ACTIVOS
                and intento_existente.expira_en <= ahora
            ):
                intento_existente.estado = "expirado"
                db.flush()
                intento_solicitud_no_disponible = True
            elif intento_existente.estado in _ESTADOS_INTENTO_ACTIVOS:
                return _dto_intento(intento_existente, cuenta.correo)
            else:
                intento_solicitud_no_disponible = True

        if not intento_solicitud_no_disponible:
            cliente = db.scalar(
                select(Cliente)
                .where(Cliente.cuenta_cliente_id == cuenta.id)
                .with_for_update()
            )
            if cliente is not None:
                tiene_membresia_vigente = db.scalar(
                    select(Membresia.id)
                    .where(
                        Membresia.cliente_id == cliente.id,
                        Membresia.estado_stripe.in_(_ESTADOS_MEMBRESIA_VIGENTE),
                    )
                    .limit(1)
                )
                if tiene_membresia_vigente is not None:
                    raise MembresiaVigenteError

            intentos_activos = list(
                db.scalars(
                    select(IntentoCheckoutCliente)
                    .where(
                        IntentoCheckoutCliente.cuenta_cliente_id == cuenta.id,
                        IntentoCheckoutCliente.estado.in_(_ESTADOS_INTENTO_ACTIVOS),
                    )
                    .with_for_update()
                )
                .all()
            )
            for intento in intentos_activos:
                if intento.expira_en <= ahora:
                    intento.estado = "expirado"
                else:
                    raise IntentoCheckoutEnCursoError

            identificador = uuid4()
            intento = IntentoCheckoutCliente(
                id=identificador,
                cuenta_cliente_id=cuenta.id,
                clave_solicitud=clave_solicitud,
                stripe_idempotency_key=f"sp_checkout_cliente_{identificador.hex}",
                stripe_customer_id=(
                    cliente.stripe_customer_id if cliente is not None else None
                ),
                estado="creado",
                expira_en=ahora + _DURACION_CHECKOUT,
            )
            db.add(intento)
            db.flush()
            resultado = _dto_intento(intento, cuenta.correo)

    if intento_solicitud_no_disponible:
        raise IntentoCheckoutNoDisponibleError
    if resultado is None:
        raise IntentoCheckoutNoDisponibleError
    return resultado


def _dto_intento(intento: IntentoCheckoutCliente, correo: str) -> IntentoCheckoutDTO:
    return IntentoCheckoutDTO(
        id=intento.id,
        cuenta_cliente_id=intento.cuenta_cliente_id,
        correo=correo,
        clave_solicitud=intento.clave_solicitud,
        stripe_idempotency_key=intento.stripe_idempotency_key,
        checkout_session_id=intento.checkout_session_id,
        stripe_customer_id=intento.stripe_customer_id,
        expira_en=intento.expira_en,
    )


def guardar_checkout_creado(
    db: Session,
    *,
    intento_id: UUID,
    checkout_session_id: str,
    stripe_customer_id: str | None,
    expira_en: datetime,
) -> None:
    """Guarda el resultado Stripe sin reabrir un intento ya confirmado."""

    db.rollback()
    with db.begin():
        intento = db.scalar(
            select(IntentoCheckoutCliente)
            .where(IntentoCheckoutCliente.id == intento_id)
            .with_for_update()
        )
        if intento is None or intento.estado not in _ESTADOS_INTENTO_ACTIVOS:
            raise IntentoCheckoutNoDisponibleError
        intento.checkout_session_id = checkout_session_id
        intento.stripe_customer_id = stripe_customer_id
        intento.expira_en = expira_en
        intento.estado = "abierto"


def consultar_estado_intento_checkout(
    db: Session,
    *,
    cuenta_cliente_id: int,
    checkout_session_id: str,
) -> str:
    """El retorno de Stripe solo refleja la confirmacion guardada por webhook."""

    intento = db.scalar(
        select(IntentoCheckoutCliente).where(
            IntentoCheckoutCliente.cuenta_cliente_id == cuenta_cliente_id,
            IntentoCheckoutCliente.checkout_session_id == checkout_session_id,
        )
    )
    if intento is None:
        return "no_completado"
    if intento.estado == "confirmado":
        return "confirmado"
    if intento.estado in {"expirado", "fallido"}:
        return "no_completado"
    return "pendiente"


__all__ = [
    "ClienteNoEncontradoError",
    "DetalleMembresiaCuentaDTO",
    "DetalleMembresiaDTO",
    "IntentoCheckoutDTO",
    "IntentoCheckoutEnCursoError",
    "IntentoCheckoutNoDisponibleError",
    "MembresiaCuentaDTO",
    "MembresiaVigenteError",
    "PaginaClientesDTO",
    "TAMANO_PAGINA_CLIENTES",
    "consultar_estado_intento_checkout",
    "crear_o_reusar_intento_checkout",
    "formatear_codigo_cliente",
    "guardar_checkout_creado",
    "listar_clientes",
    "obtener_detalle_membresia",
    "obtener_membresia_cuenta",
]
