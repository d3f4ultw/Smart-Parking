"""Compra publica por Checkout y lecturas administrativas OWNER-only."""

from typing import Annotated, NoReturn
from uuid import UUID

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencias_clientes import exigir_accion_cliente
from app.core.config import get_settings
from app.core.database import get_db
from app.esquemas.clientes_membresias import (
    ClienteResumen,
    DetalleMembresiaCliente,
    EstadoCheckoutPublico,
    PlanMembresiaPublico,
    RespuestaCheckout,
    RespuestaListaClientes,
    RespuestaPlanesMembresia,
    SolicitudCheckout,
)
from app.servicios.autorizacion_clientes import AccionClienteMembresia
from app.servicios.clientes_membresias import (
    ClienteNoEncontradoError,
    listar_clientes,
    obtener_detalle_membresia,
)
from app.servicios.stripe_membresias import (
    MembresiasNoDisponiblesError,
    StripeMembresiasError,
    StripeNoConfiguradoError,
    consultar_estado_checkout,
    crear_checkout_membresia,
    crear_cliente_stripe,
    exigir_membresias_disponibles,
    listar_planes_membresia,
)

RUTA_MEMBRESIAS = "/api/membresias"
RUTA_ADMIN_CLIENTES = "/api/admin/clientes"
TAMANO_PAGINA_CLIENTES = 10
CABECERA_NO_CACHE = {"Cache-Control": "no-store"}

router_membresias = APIRouter(prefix=RUTA_MEMBRESIAS, tags=["membresias"])
router_clientes = APIRouter(prefix=RUTA_ADMIN_CLIENTES, tags=["admin-clientes"])


def _error_configuracion() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="El servicio de membresias no esta disponible.",
        headers=CABECERA_NO_CACHE,
    ) from None


@router_membresias.get("/planes", response_model=RespuestaPlanesMembresia)
def consultar_planes_membresia(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaPlanesMembresia:
    response.headers.update(CABECERA_NO_CACHE)
    try:
        exigir_membresias_disponibles(db)
        settings = get_settings()
        planes = listar_planes_membresia(
            crear_cliente_stripe(settings),
            settings,
        )
        db.rollback()
        return RespuestaPlanesMembresia(
            planes=[PlanMembresiaPublico.model_validate(plan) for plan in planes]
        )
    except MembresiasNoDisponiblesError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Las membresias solo estan disponibles en modalidades "
                "Comercial y Mixta."
            ),
            headers=CABECERA_NO_CACHE,
        ) from None
    except StripeNoConfiguradoError:
        db.rollback()
        _error_configuracion()
    except (StripeMembresiasError, stripe.StripeError):
        db.rollback()
        _error_configuracion()
    except SQLAlchemyError:
        db.rollback()
        _error_configuracion()


@router_membresias.post("/checkout", response_model=RespuestaCheckout)
def crear_checkout_endpoint(
    solicitud: SolicitudCheckout,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    clave_idempotencia: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> RespuestaCheckout:
    response.headers.update(CABECERA_NO_CACHE)
    settings = get_settings()
    try:
        exigir_membresias_disponibles(db)
        url = crear_checkout_membresia(
            crear_cliente_stripe(settings),
            settings,
            plan_id=solicitud.plan_id,
            clave_idempotencia=clave_idempotencia,
        )
        db.rollback()
        return RespuestaCheckout(checkout_url=url)
    except MembresiasNoDisponiblesError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Las membresias solo estan disponibles en modalidades "
                "Comercial y Mixta."
            ),
            headers=CABECERA_NO_CACHE,
        ) from None
    except StripeNoConfiguradoError:
        db.rollback()
        _error_configuracion()
    except (StripeMembresiasError, stripe.StripeError):
        db.rollback()
        _error_configuracion()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de membresias no esta disponible.",
            headers=CABECERA_NO_CACHE,
        ) from None


@router_membresias.get(
    "/checkout/{checkout_session_id}/estado",
    response_model=EstadoCheckoutPublico,
)
def consultar_estado_checkout_endpoint(
    checkout_session_id: str,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> EstadoCheckoutPublico:
    response.headers.update(CABECERA_NO_CACHE)
    settings = get_settings()
    try:
        estado = consultar_estado_checkout(
            crear_cliente_stripe(settings),
            db,
            checkout_session_id=checkout_session_id,
        )
        db.rollback()
        return EstadoCheckoutPublico.model_validate({"estado": estado})
    except StripeNoConfiguradoError:
        db.rollback()
        _error_configuracion()
    except (StripeMembresiasError, stripe.StripeError):
        db.rollback()
        _error_configuracion()
    except SQLAlchemyError:
        db.rollback()
        _error_configuracion()


@router_clientes.get("", response_model=RespuestaListaClientes)
def consultar_clientes(
    response: Response,
    _usuario_id: Annotated[
        int,
        Depends(exigir_accion_cliente(AccionClienteMembresia.LEER)),
    ],
    db: Annotated[Session, Depends(get_db)],
    pagina: Annotated[int, Query(ge=1)] = 1,
) -> RespuestaListaClientes:
    response.headers.update(CABECERA_NO_CACHE)
    try:
        resultado = listar_clientes(db, pagina=pagina)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno",
            headers=CABECERA_NO_CACHE,
        ) from None
    return RespuestaListaClientes(
        clientes=[
            ClienteResumen(
                codigo_cliente=fila.codigo_cliente,
                nombre_completo=fila.nombre_completo,
                estado_membresia=fila.estado_membresia,
            )
            for fila in resultado.clientes
        ],
        pagina=resultado.pagina,
        tamano_pagina=resultado.tamano_pagina,
        total=resultado.total,
        total_paginas=resultado.total_paginas,
    )


@router_clientes.get("/{codigo_cliente}", response_model=DetalleMembresiaCliente)
def consultar_detalle_cliente(
    codigo_cliente: str,
    response: Response,
    _usuario_id: Annotated[
        int,
        Depends(exigir_accion_cliente(AccionClienteMembresia.DETALLE)),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> DetalleMembresiaCliente:
    response.headers.update(CABECERA_NO_CACHE)
    try:
        detalle = obtener_detalle_membresia(db, codigo_cliente=codigo_cliente)
    except ClienteNoEncontradoError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El cliente no esta disponible.",
            headers=CABECERA_NO_CACHE,
        ) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno",
            headers=CABECERA_NO_CACHE,
        ) from None
    return DetalleMembresiaCliente(
        codigo_cliente=detalle.codigo_cliente,
        plan=detalle.plan,
        monto_centavos=detalle.monto_centavos,
        moneda=detalle.moneda,
        fecha_inicio=detalle.fecha_inicio,
        proxima_renovacion=detalle.proxima_renovacion,
        estado=detalle.estado,
        cancelacion_programada=detalle.cancelacion_programada,
    )


__all__ = [
    "RUTA_ADMIN_CLIENTES",
    "RUTA_MEMBRESIAS",
    "router_clientes",
    "router_membresias",
]
