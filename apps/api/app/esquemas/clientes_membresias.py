"""Contratos privados de consulta y publicos de compra para membresias."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SolicitudCheckout(BaseModel):
    """Acepta solo una clave logica; precio e importe nunca vienen del navegador."""

    model_config = ConfigDict(extra="forbid")

    plan_id: Literal["mensual"]


class PlanMembresiaPublico(BaseModel):
    """Datos comerciales obtenidos del Price configurado en el servidor."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    nombre: str
    monto_centavos: Annotated[int, Field(ge=0)]
    moneda: Annotated[str, Field(min_length=3, max_length=3)]
    intervalo: str
    intervalo_cantidad: Annotated[int, Field(ge=1)]


class RespuestaPlanesMembresia(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planes: list[PlanMembresiaPublico]


class RespuestaCheckout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkout_url: str


class EstadoCheckoutPublico(BaseModel):
    """Estado generico; no revela identidad ni confirma altas desde el retorno."""

    model_config = ConfigDict(extra="forbid")

    estado: Literal["pendiente", "confirmado", "no_completado"]


class ClienteResumen(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codigo_cliente: str
    nombre_completo: str
    estado_membresia: str


class RespuestaListaClientes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clientes: list[ClienteResumen]
    pagina: int
    tamano_pagina: int
    total: int
    total_paginas: int


class DetalleMembresiaCliente(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codigo_cliente: str
    plan: str
    monto_centavos: int
    moneda: str
    fecha_inicio: datetime | None
    proxima_renovacion: datetime | None
    estado: str
    cancelacion_programada: bool


__all__ = [
    "ClienteResumen",
    "DetalleMembresiaCliente",
    "EstadoCheckoutPublico",
    "PlanMembresiaPublico",
    "RespuestaCheckout",
    "RespuestaListaClientes",
    "RespuestaPlanesMembresia",
    "SolicitudCheckout",
]
