"""Cambio transaccional de contrasena y revocacion de sesiones cliente."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import CuentaCliente, SesionCliente
from app.seguridad.contrasenas import (
    crear_hash_contrasena,
    validar_confirmacion_contrasena,
    verificar_contrasena,
)
from app.seguridad.sesiones import hash_token_sesion


class SesionClienteNoVigenteError(ValueError):
    """La sesion cliente ya no puede autorizar un cambio de credenciales."""


def cambiar_contrasena_cliente(
    db: Session,
    *,
    cuenta_cliente_id: int,
    token_sesion_actual: str,
    contrasena_actual: str,
    contrasena_nueva: str,
    confirmacion_contrasena_nueva: str,
    ahora: datetime | None = None,
) -> int | None:
    """Actualiza la cuenta y revoca todas sus sesiones salvo la solicitante.

    Devuelve el numero de sesiones revocadas, o ``None`` si la contrasena
    actual no coincide. La sesion que realizo el cambio permanece activa para
    permitir continuar de forma segura en el mismo dispositivo.
    """

    validar_confirmacion_contrasena(
        contrasena_nueva,
        confirmacion_contrasena_nueva,
    )
    instante = ahora or datetime.now(UTC)
    hash_sesion_actual = hash_token_sesion(token_sesion_actual)

    try:
        cuenta = db.scalar(
            select(CuentaCliente)
            .where(CuentaCliente.id == cuenta_cliente_id)
            .with_for_update()
        )
        if cuenta is None or not cuenta.esta_activa:
            raise SesionClienteNoVigenteError

        if not verificar_contrasena(contrasena_actual, cuenta.contrasena_hash):
            db.rollback()
            return None

        sesiones = list(
            db.scalars(
                select(SesionCliente)
                .where(
                    SesionCliente.cuenta_cliente_id == cuenta.id,
                    SesionCliente.revocada_en.is_(None),
                )
                .with_for_update()
            ).all()
        )
        sesion_actual = next(
            (
                sesion
                for sesion in sesiones
                if sesion.token_hash == hash_sesion_actual
            ),
            None,
        )
        if sesion_actual is None or sesion_actual.expira_en <= instante:
            raise SesionClienteNoVigenteError

        cuenta.contrasena_hash = crear_hash_contrasena(contrasena_nueva)
        sesiones_revocadas = 0
        for sesion in sesiones:
            if sesion.id != sesion_actual.id:
                sesion.revocada_en = instante
                sesiones_revocadas += 1

        db.commit()
        return sesiones_revocadas
    except SQLAlchemyError:
        db.rollback()
        raise
    except SesionClienteNoVigenteError:
        db.rollback()
        raise


__all__ = ["SesionClienteNoVigenteError", "cambiar_contrasena_cliente"]
