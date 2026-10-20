"""Limitadores independientes para autenticacion de clientes."""

from app.seguridad.limitador import LimitadorAutenticacion

# El login de cliente tiene contadores propios, separados del acceso de personal.
limitador_autenticacion_clientes = LimitadorAutenticacion()

__all__ = ["limitador_autenticacion_clientes"]
