"""Rutas HTTP de Smart Parking."""

from app.api.rutas.activaciones import (
    reenviar_router as reenvio_activacion_router,
)
from app.api.rutas.activaciones import (
    router as activaciones_router,
)
from app.api.rutas.activaciones_operador import (
    RUTA_ACTIVACION_OPERADOR,
)
from app.api.rutas.activaciones_operador import (
    router as activaciones_operador_router,
)
from app.api.rutas.activaciones_propietario import (
    RUTA_ACTIVACION_PROPIETARIO,
)
from app.api.rutas.activaciones_propietario import (
    router as activaciones_propietario_router,
)
from app.api.rutas.autenticacion import (
    RUTA_LOGIN,
    RUTA_LOGOUT,
    RUTA_ME,
)
from app.api.rutas.autenticacion import (
    router as autenticacion_router,
)
from app.api.rutas.cajones import router as cajones_router
from app.api.rutas.eventos import router as eventos_tiempo_real_router
from app.api.rutas.gestion_propietario import (
    RUTA_GESTION_PROPIETARIO,
)
from app.api.rutas.gestion_propietario import (
    router as gestion_propietario_router,
)
from app.api.rutas.operadores import (
    RUTA_CREAR_OPERADOR,
)
from app.api.rutas.operadores import (
    router as operadores_router,
)

__all__ = [
    "RUTA_LOGIN",
    "RUTA_LOGOUT",
    "RUTA_ME",
    "RUTA_CREAR_OPERADOR",
    "RUTA_ACTIVACION_OPERADOR",
    "RUTA_ACTIVACION_PROPIETARIO",
    "RUTA_GESTION_PROPIETARIO",
    "activaciones_router",
    "activaciones_operador_router",
    "activaciones_propietario_router",
    "autenticacion_router",
    "cajones_router",
    "eventos_tiempo_real_router",
    "gestion_propietario_router",
    "operadores_router",
    "reenvio_activacion_router",
]
