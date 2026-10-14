"""Servicios transaccionales para crear usuarios de Smart Parking."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ActivacionCuenta, RolUsuario, Usuario
from app.seguridad.activaciones import generar_token_activacion, hash_token_activacion
from app.seguridad.correos import (
    CorreoInvalidoError,
    normalizar_correo,
)
from app.servicios.eventos_operadores import registrar_evento_operador


class DatoPersonalInvalidoError(ValueError):
    """Dato personal requerido ausente o demasiado largo."""


class ErrorCreacionOperador(ValueError):
    """Clase base para errores esperados y seguros al crear un OPERADOR."""


class DatoOperadorInvalidoError(ErrorCreacionOperador):
    """Se lanza cuando falta o excede de longitud un dato del OPERADOR."""


class CorreoOperadorDuplicadoError(ErrorCreacionOperador):
    """Se lanza cuando un correo ya pertenece a una cuenta."""

    def __init__(self) -> None:
        super().__init__("El correo ya esta registrado.")


@dataclass(frozen=True, slots=True)
class DatosOperador:
    """Datos validados y normalizados usados por la creacion de OPERADOR."""

    nombre: str
    apellido_paterno: str
    apellido_materno: str
    correo: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ResultadoCreacionOperador:
    """Resultado interno de la creacion de un OPERADOR."""

    usuario: Usuario


_LONGITUDES_DATOS = {
    "nombre": 100,
    "apellido_paterno": 100,
    "apellido_materno": 100,
}
_ETIQUETAS_DATOS = {
    "nombre": "El nombre",
    "apellido_paterno": "El apellido paterno",
    "apellido_materno": "El apellido materno",
}


def _validar_texto_requerido(valor: str, campo: str) -> str:
    etiqueta = _ETIQUETAS_DATOS[campo]
    if not isinstance(valor, str):
        raise DatoPersonalInvalidoError(f"{etiqueta} es obligatorio.")
    valor_normalizado = valor.strip()
    if not valor_normalizado:
        raise DatoPersonalInvalidoError(f"{etiqueta} es obligatorio.")
    longitud_maxima = _LONGITUDES_DATOS[campo]
    if len(valor_normalizado) > longitud_maxima:
        raise DatoPersonalInvalidoError(
            f"{etiqueta} no puede superar {longitud_maxima} caracteres."
        )
    return valor_normalizado


def preparar_datos_operador(
    *,
    nombre: str,
    apellido_paterno: str,
    apellido_materno: str,
    correo: str,
) -> DatosOperador:
    """Valida los datos de OPERADOR con las reglas canonicas del usuario."""

    correo_normalizado = normalizar_correo(correo)
    if len(correo_normalizado) > 320:
        raise CorreoInvalidoError("El correo no es valido.")

    try:
        return DatosOperador(
            nombre=_validar_texto_requerido(nombre, "nombre"),
            apellido_paterno=_validar_texto_requerido(
                apellido_paterno, "apellido_paterno"
            ),
            apellido_materno=_validar_texto_requerido(
                apellido_materno, "apellido_materno"
            ),
            correo=correo_normalizado,
        )
    except DatoPersonalInvalidoError as error:
        raise DatoOperadorInvalidoError(str(error)) from error


def _es_duplicado_de_correo(error: IntegrityError) -> bool:
    original = error.orig
    diagnostico = getattr(original, "diag", None)
    nombre_restriccion = getattr(diagnostico, "constraint_name", None)
    if nombre_restriccion == "ix_usuarios_correo":
        return True
    detalle = str(original)
    return "ix_usuarios_correo" in detalle or "usuarios.correo" in detalle


def crear_operador(
    db: Session,
    *,
    nombre: str,
    apellido_paterno: str,
    apellido_materno: str,
    correo: str,
    creado_por_usuario_id: int | None = None,
    entregar_invitacion: Callable[[Usuario, str], None],
    duracion_token_horas: int,
    ahora: datetime | None = None,
) -> ResultadoCreacionOperador:
    """Crea un OPERADOR pendiente y entrega su enlace dentro de la transaccion."""

    datos = preparar_datos_operador(
        nombre=nombre,
        apellido_paterno=apellido_paterno,
        apellido_materno=apellido_materno,
        correo=correo,
    )
    if not 1 <= duracion_token_horas <= 168:
        raise ValueError("La vigencia de la invitacion no es valida.")

    ahora_utc = ahora or datetime.now(UTC)
    if ahora_utc.tzinfo is None or ahora_utc.utcoffset() is None:
        raise ValueError("La fecha de invitacion debe incluir zona horaria.")
    ahora_utc = ahora_utc.astimezone(UTC)
    token = generar_token_activacion()

    try:
        with db.begin():
            existente = db.scalar(
                select(Usuario.id).where(Usuario.correo == datos.correo)
            )
            if existente is not None:
                raise CorreoOperadorDuplicadoError

            usuario = Usuario(
                nombre=datos.nombre,
                apellido_paterno=datos.apellido_paterno,
                apellido_materno=datos.apellido_materno,
                correo=datos.correo,
                contrasena_hash=None,
                rol=RolUsuario.OPERADOR.value,
                correo_verificado=False,
                esta_activo=True,
                debe_cambiar_contrasena=False,
                creado_por_usuario_id=creado_por_usuario_id,
            )
            db.add(usuario)
            db.flush()
            activacion = ActivacionCuenta(
                usuario_id=usuario.id,
                token_hash=hash_token_activacion(token),
                codigo_hash=None,
                expira_en=ahora_utc + timedelta(hours=duracion_token_horas),
                consumido_en=None,
                creado_en=ahora_utc,
            )
            db.add(activacion)
            db.flush()
            entregar_invitacion(usuario, token)
            registrar_evento_operador(db, usuario.id, "operador.creado")
    except IntegrityError as error:
        db.rollback()
        if _es_duplicado_de_correo(error):
            raise CorreoOperadorDuplicadoError from error
        raise
    finally:
        del token

    return ResultadoCreacionOperador(usuario=usuario)


__all__ = [
    "CorreoOperadorDuplicadoError",
    "CorreoInvalidoError",
    "DatoOperadorInvalidoError",
    "DatosOperador",
    "ErrorCreacionOperador",
    "ResultadoCreacionOperador",
    "crear_operador",
    "preparar_datos_operador",
]
