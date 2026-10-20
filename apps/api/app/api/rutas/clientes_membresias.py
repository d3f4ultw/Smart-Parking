"""Checkout autenticado de clientes y lecturas administrativas OWNER-only."""

from typing import Annotated, Literal, NoReturn
from urllib.parse import urlsplit
from uuid import UUID

import stripe
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencias_clientes import exigir_accion_cliente
from app.api.dependencias_sesion_cliente import exigir_cuenta_cliente
from app.core.config import get_settings
from app.core.database import get_db
from app.esquemas.clientes_membresias import (
    ClienteResumen,
    DetalleMembresiaCliente,
    EstadoCheckoutPublico,
    MembresiaCuentaCliente,
    PlanMembresiaPublico,
    RespuestaCheckout,
    RespuestaListaClientes,
    RespuestaPlanesMembresia,
    SolicitudCheckout,
)
from app.models import CuentaCliente
from app.servicios.autorizacion_clientes import AccionClienteMembresia
from app.servicios.clientes_membresias import (
    ClienteNoEncontradoError,
    IntentoCheckoutEnCursoError,
    IntentoCheckoutNoDisponibleError,
    MembresiaVigenteError,
    consultar_estado_intento_checkout,
    crear_o_reusar_intento_checkout,
    guardar_checkout_creado,
    listar_clientes,
    obtener_detalle_membresia,
    obtener_membresia_cuenta,
)
from app.servicios.stripe_membresias import (
    MembresiasNoDisponiblesError,
    StripeMembresiasError,
    StripeNoConfiguradoError,
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
router_cliente = APIRouter(prefix="/api/clientes", tags=["clientes-membresias"])


def _error_configuracion() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="El servicio de membresias no esta disponible.",
        headers=CABECERA_NO_CACHE,
    ) from None


def _exigir_origen_checkout(request: Request) -> None:
    """Requiere el Origin exacto del sitio configurado para iniciar una compra."""

    try:
        configurado = urlsplit(get_settings().app_public_url)
    except ValueError:
        _error_configuracion()
    esperado = f"{configurado.scheme}://{configurado.netloc}"
    if not configurado.scheme or not configurado.netloc:
        _error_configuracion()
    if request.headers.get("origin") != esperado:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origen no autorizado.",
            headers=CABECERA_NO_CACHE,
        )


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


def _abrir_checkout(
    db: Session,
    *,
    cuenta: CuentaCliente,
    clave_solicitud: UUID,
) -> str:
    settings = get_settings()
    exigir_membresias_disponibles(db)
    cliente_stripe = crear_cliente_stripe(settings)
    intento = crear_o_reusar_intento_checkout(
        db,
        cuenta_cliente_id=cuenta.id,
        clave_solicitud=clave_solicitud,
    )
    resultado = crear_checkout_membresia(
        cliente_stripe,
        settings,
        plan_id="mensual",
        intento_id=intento.id,
        clave_idempotencia=intento.stripe_idempotency_key,
        expira_en=intento.expira_en,
        correo_cliente=intento.correo,
        stripe_customer_id=intento.stripe_customer_id,
    )
    guardar_checkout_creado(
        db,
        intento_id=intento.id,
        checkout_session_id=resultado["checkout_session_id"],
        stripe_customer_id=resultado["stripe_customer_id"],
        expira_en=resultado["expira_en"],
    )
    return resultado["checkout_url"]


@router_membresias.post("/checkout", response_model=RespuestaCheckout)
def crear_checkout_endpoint(
    solicitud: SolicitudCheckout,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    cuenta: Annotated[CuentaCliente, Depends(exigir_cuenta_cliente)],
    clave_solicitud: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> RespuestaCheckout:
    response.headers.update(CABECERA_NO_CACHE)
    _exigir_origen_checkout(request)
    try:
        url = _abrir_checkout(
            db,
            cuenta=cuenta,
            clave_solicitud=clave_solicitud,
        )
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
    except (IntentoCheckoutEnCursoError, MembresiaVigenteError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una membresia o compra pendiente para esta cuenta.",
            headers=CABECERA_NO_CACHE,
        ) from None
    except IntentoCheckoutNoDisponibleError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La solicitud de compra ya no esta disponible.",
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


@router_membresias.get(
    "/checkout/{checkout_session_id}/estado",
    response_model=EstadoCheckoutPublico,
)
def consultar_estado_checkout_endpoint(
    checkout_session_id: str,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    cuenta: Annotated[CuentaCliente, Depends(exigir_cuenta_cliente)],
) -> EstadoCheckoutPublico:
    response.headers.update(CABECERA_NO_CACHE)
    try:
        estado = consultar_estado_intento_checkout(
            db,
            cuenta_cliente_id=cuenta.id,
            checkout_session_id=checkout_session_id,
        )
        db.rollback()
        return EstadoCheckoutPublico.model_validate({"estado": estado})
    except SQLAlchemyError:
        db.rollback()
        _error_configuracion()


@router_cliente.get("/membresia", response_model=MembresiaCuentaCliente)
def consultar_membresia_cuenta(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    cuenta: Annotated[CuentaCliente, Depends(exigir_cuenta_cliente)],
) -> MembresiaCuentaCliente:
    response.headers.update(CABECERA_NO_CACHE)
    try:
        membresia = obtener_membresia_cuenta(db, cuenta_cliente_id=cuenta.id)
        db.rollback()
    except SQLAlchemyError:
        db.rollback()
        _error_configuracion()
    return MembresiaCuentaCliente.model_validate(
        {
            "estado": membresia.estado,
            "membresia": (
                {
                    "plan": membresia.membresia.plan,
                    "monto_centavos": membresia.membresia.monto_centavos,
                    "moneda": membresia.membresia.moneda,
                    "intervalo": membresia.membresia.intervalo,
                    "intervalo_cantidad": membresia.membresia.intervalo_cantidad,
                    "fecha_inicio": membresia.membresia.fecha_inicio,
                    "periodo_actual_inicio": membresia.membresia.periodo_actual_inicio,
                    "periodo_actual_fin": membresia.membresia.periodo_actual_fin,
                    "cancelacion_programada": (
                        membresia.membresia.cancelacion_programada
                    ),
                }
                if membresia.membresia is not None
                else None
            ),
            "checkout_pendiente": membresia.checkout_pendiente,
            "puede_comprar": membresia.puede_comprar,
        }
    )


@router_clientes.get("", response_model=RespuestaListaClientes)
def consultar_clientes(
    response: Response,
    _usuario_id: Annotated[
        int,
        Depends(exigir_accion_cliente(AccionClienteMembresia.LEER)),
    ],
    db: Annotated[Session, Depends(get_db)],
    pagina: Annotated[int, Query(ge=1)] = 1,
    estado: Annotated[
        Literal["sin_membresia", "activa", "cancelada"] | None,
        Query(),
    ] = None,
) -> RespuestaListaClientes:
    response.headers.update(CABECERA_NO_CACHE)
    try:
        resultado = listar_clientes(db, pagina=pagina, estado=estado)
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
    "router_cliente",
    "router_clientes",
    "router_membresias",
]
