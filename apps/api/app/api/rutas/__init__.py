"""Rutas HTTP de Smart Parking."""

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
from app.api.rutas.autenticacion_clientes import (
    RUTA_LOGIN_CLIENTE,
    RUTA_LOGOUT_CLIENTE,
    RUTA_ME_CLIENTE,
)
from app.api.rutas.autenticacion_clientes import (
    router as autenticacion_clientes_router,
)
from app.api.rutas.cajones import router as cajones_router
from app.api.rutas.clientes_membresias import (
    RUTA_ADMIN_CLIENTES,
    RUTA_MEMBRESIAS,
)
from app.api.rutas.clientes_membresias import (
    router_cliente as cliente_membresia_router,
)
from app.api.rutas.clientes_membresias import (
    router_clientes as clientes_router,
)
from app.api.rutas.clientes_membresias import (
    router_membresias as membresias_router,
)
from app.api.rutas.configuracion_estacionamiento import (
    RUTA_CONFIGURACION_ACCESO,
    RUTA_CONFIGURACION_MODALIDAD,
)
from app.api.rutas.configuracion_estacionamiento import (
    router as configuracion_estacionamiento_router,
)
from app.api.rutas.configuracion_estacionamiento import (
    router_acceso as configuracion_acceso_router,
)
from app.api.rutas.contrasena_clientes import (
    router as contrasena_clientes_router,
)
from app.api.rutas.cuentas_clientes import (
    RUTA_REGISTRO_CLIENTE,
)
from app.api.rutas.cuentas_clientes import (
    router as cuentas_clientes_router,
)
from app.api.rutas.empleados import RUTA_ADMIN_EMPLEADOS
from app.api.rutas.empleados import router as empleados_router
from app.api.rutas.eventos import router as eventos_tiempo_real_router
from app.api.rutas.gestion_propietario import (
    RUTA_GESTION_PROPIETARIO,
)
from app.api.rutas.gestion_propietario import (
    router as gestion_propietario_router,
)
from app.api.rutas.horarios_empleados import (
    RUTA_HORARIOS_EMPLEADOS,
)
from app.api.rutas.horarios_empleados import (
    router as horarios_empleados_router,
)
from app.api.rutas.operadores import (
    RUTA_CREAR_OPERADOR,
)
from app.api.rutas.operadores import (
    router as operadores_router,
)
from app.api.rutas.stripe_webhook import (
    RUTA_STRIPE_WEBHOOK,
)
from app.api.rutas.stripe_webhook import (
    router as stripe_webhook_router,
)
from app.api.rutas.vision import router as vision_router
from app.api.rutas.vision_owner import router as vision_owner_router
from app.api.rutas.vision_owner import router_vision as vision_frames_router

__all__ = [
    "RUTA_LOGIN",
    "RUTA_LOGOUT",
    "RUTA_ME",
    "RUTA_LOGIN_CLIENTE",
    "RUTA_LOGOUT_CLIENTE",
    "RUTA_ME_CLIENTE",
    "RUTA_CREAR_OPERADOR",
    "RUTA_ADMIN_CLIENTES",
    "RUTA_MEMBRESIAS",
    "RUTA_REGISTRO_CLIENTE",
    "RUTA_STRIPE_WEBHOOK",
    "RUTA_ACTIVACION_OPERADOR",
    "RUTA_ACTIVACION_PROPIETARIO",
    "RUTA_CONFIGURACION_MODALIDAD",
    "RUTA_CONFIGURACION_ACCESO",
    "RUTA_GESTION_PROPIETARIO",
    "RUTA_HORARIOS_EMPLEADOS",
    "RUTA_ADMIN_EMPLEADOS",
    "activaciones_operador_router",
    "activaciones_propietario_router",
    "autenticacion_router",
    "autenticacion_clientes_router",
    "contrasena_clientes_router",
    "cajones_router",
    "clientes_router",
    "cliente_membresia_router",
    "cuentas_clientes_router",
    "configuracion_estacionamiento_router",
    "configuracion_acceso_router",
    "eventos_tiempo_real_router",
    "empleados_router",
    "gestion_propietario_router",
    "horarios_empleados_router",
    "membresias_router",
    "operadores_router",
    "vision_router",
    "vision_owner_router",
    "vision_frames_router",
    "stripe_webhook_router",
]
