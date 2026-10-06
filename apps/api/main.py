from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.api.rutas import (
    RUTA_ACTIVACION_OPERADOR,
    RUTA_CREAR_OPERADOR,
    RUTA_LOGIN,
    RUTA_LOGOUT,
    RUTA_ME,
    activaciones_operador_router,
    activaciones_router,
    autenticacion_router,
    eventos_tiempo_real_router,
    operadores_router,
    reenvio_activacion_router,
)
from app.api.rutas.eventos import cerrar_leases_sse_activas
from app.core.config import get_settings
from app.core.database import engine
from app.correo.smtp import cargar_configuracion_smtp
from app.models import ActivacionCuenta, Sesion, Usuario  # noqa: F401


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Valida SMTP antes de recibir trafico cuando ese transporte esta activo."""

    settings = get_settings()
    if settings.correo_transporte == "smtp":
        cargar_configuracion_smtp(settings)
    try:
        yield
    finally:
        await cerrar_leases_sse_activas()


app = FastAPI(title="Smart Parking API", lifespan=lifespan)
app.state.database_engine = engine
app.include_router(autenticacion_router)
app.include_router(eventos_tiempo_real_router)
app.include_router(operadores_router)
app.include_router(activaciones_operador_router)
app.include_router(activaciones_router)
app.include_router(reenvio_activacion_router)
RUTAS_ACTIVACION = frozenset(
    {
        "/api/autenticacion/activar/manual",
        "/api/autenticacion/activar/temporal",
        "/api/autenticacion/activacion/prevalidar",
        "/api/autenticacion/activacion/reenviar",
    }
)
RUTAS_ACTIVACION_OPERADOR = frozenset(
    {
        f"{RUTA_ACTIVACION_OPERADOR}/enlace",
        f"{RUTA_ACTIVACION_OPERADOR}/desafio",
        f"{RUTA_ACTIVACION_OPERADOR}/completar",
    }
)
RUTAS_SIN_CACHE = (
    RUTAS_ACTIVACION
    | RUTAS_ACTIVACION_OPERADOR
    | {
        RUTA_CREAR_OPERADOR,
        RUTA_LOGIN,
        RUTA_LOGOUT,
        RUTA_ME,
    }
)


@app.middleware("http")
async def evitar_cache_en_autenticacion(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Evita cachear respuestas de los endpoints de autenticacion."""

    response = await call_next(request)
    if request.url.path in RUTAS_SIN_CACHE:
        response.headers["Cache-Control"] = "no-store"
    if request.url.path in RUTAS_ACTIVACION_OPERADOR:
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
