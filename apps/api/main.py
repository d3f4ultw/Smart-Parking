from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.api.rutas import (
    RUTA_ACTIVACION_OPERADOR,
    RUTA_ACTIVACION_PROPIETARIO,
    RUTA_ADMIN_CLIENTES,
    RUTA_ADMIN_EMPLEADOS,
    RUTA_CONFIGURACION_ACCESO,
    RUTA_CONFIGURACION_MODALIDAD,
    RUTA_CREAR_OPERADOR,
    RUTA_HORARIOS_EMPLEADOS,
    RUTA_LOGIN,
    RUTA_LOGOUT,
    RUTA_ME,
    RUTA_MEMBRESIAS,
    RUTA_STRIPE_WEBHOOK,
    activaciones_operador_router,
    activaciones_propietario_router,
    autenticacion_router,
    cajones_router,
    clientes_router,
    configuracion_acceso_router,
    configuracion_estacionamiento_router,
    empleados_router,
    eventos_tiempo_real_router,
    gestion_propietario_router,
    horarios_empleados_router,
    membresias_router,
    operadores_router,
    stripe_webhook_router,
    vision_frames_router,
    vision_owner_router,
    vision_router,
)
from app.api.rutas.eventos import cerrar_leases_sse_activas
from app.core.config import get_settings
from app.core.database import engine
from app.correo.smtp import cargar_configuracion_smtp
from app.models import (  # noqa: F401
    ActivacionCuenta,
    Cliente,
    CuentaPropietario,
    Empleado,
    EventoStripe,
    FacturaMembresia,
    InscripcionPropietario,
    Membresia,
    Sesion,
    SesionGestionPropietario,
    TurnoEmpleado,
    Usuario,
)
from app.servicios.vision_frames import VisionFrameHub


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Valida SMTP antes de recibir trafico cuando ese transporte esta activo."""

    settings = get_settings()
    _app.state.vision_frame_hub = VisionFrameHub()
    if settings.correo_transporte == "smtp":
        cargar_configuracion_smtp(settings)
    try:
        yield
    finally:
        await _app.state.vision_frame_hub.cerrar()
        await cerrar_leases_sse_activas()


app = FastAPI(title="Smart Parking API", lifespan=lifespan)
app.state.database_engine = engine


app.include_router(autenticacion_router)
app.include_router(configuracion_estacionamiento_router)
app.include_router(configuracion_acceso_router)
app.include_router(horarios_empleados_router)
app.include_router(empleados_router)
app.include_router(clientes_router)
app.include_router(membresias_router)
app.include_router(stripe_webhook_router)
app.include_router(eventos_tiempo_real_router)
app.include_router(cajones_router)
app.include_router(vision_router)
app.include_router(vision_frames_router)
app.include_router(vision_owner_router)
app.include_router(operadores_router)
app.include_router(activaciones_operador_router)
app.include_router(activaciones_propietario_router)
app.include_router(gestion_propietario_router)
RUTAS_ACTIVACION_OPERADOR = frozenset(
    {
        f"{RUTA_ACTIVACION_OPERADOR}/enlace",
        f"{RUTA_ACTIVACION_OPERADOR}/desafio",
        f"{RUTA_ACTIVACION_OPERADOR}/completar",
    }
)
RUTAS_ACTIVACION_PROPIETARIO = frozenset(
    {
        f"{RUTA_ACTIVACION_PROPIETARIO}/enlace",
        f"{RUTA_ACTIVACION_PROPIETARIO}/desafio",
        f"{RUTA_ACTIVACION_PROPIETARIO}/completar",
    }
)
RUTAS_SIN_CACHE = (
    RUTAS_ACTIVACION_OPERADOR
    | RUTAS_ACTIVACION_PROPIETARIO
    | {
        RUTA_CREAR_OPERADOR,
        RUTA_LOGIN,
        RUTA_LOGOUT,
        RUTA_ME,
        RUTA_CONFIGURACION_MODALIDAD,
        RUTA_CONFIGURACION_ACCESO,
        RUTA_HORARIOS_EMPLEADOS,
        RUTA_ADMIN_EMPLEADOS,
        RUTA_ADMIN_CLIENTES,
        RUTA_MEMBRESIAS,
        RUTA_STRIPE_WEBHOOK,
    }
)


@app.middleware("http")
async def evitar_cache_en_autenticacion(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Evita cachear respuestas privadas de autenticación y configuración."""

    response = await call_next(request)
    if (
        request.url.path in RUTAS_SIN_CACHE
        or request.url.path.startswith(f"{RUTA_ADMIN_EMPLEADOS}/")
        or request.url.path.startswith(f"{RUTA_ADMIN_CLIENTES}/")
        or request.url.path.startswith("/api/gestion-propietario/v1/")
    ):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path.startswith("/api/gestion-propietario/v1/"):
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    if request.url.path in RUTAS_ACTIVACION_OPERADOR | RUTAS_ACTIVACION_PROPIETARIO:
        response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    _request: Request,
    _error: RequestValidationError,
) -> JSONResponse:
    """Evita devolver valores recibidos en errores de validacion HTTP."""

    return JSONResponse(
        status_code=422,
        content={"detail": "Solicitud invalida"},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}
