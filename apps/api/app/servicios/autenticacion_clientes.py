"""Autenticacion de cuentas publicas y persistencia de sesiones cliente."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import CuentaCliente, SesionCliente
from app.seguridad.contrasenas import HASH_DUMMY_CONTRASENA, verificar_contrasena
from app.seguridad.sesiones import generar_token_sesion, hash_token_sesion


@dataclass(frozen=True, slots=True)
class ResultadoSesionCliente:
    """Sesion persistida y token efimero que solo debe llegar a la cookie."""

    sesion: SesionCliente
    token: str = field(repr=False)


def crear_sesion_cliente(
    db: Session,
    *,
    correo_normalizado: str,
    contrasena: str,
    duracion_minutos: int,
    ahora: datetime | None = None,
) -> ResultadoSesionCliente | None:
    """Valida la cuenta activa y crea una sesion aislada de la de personal."""

    try:
        cuenta = db.scalar(
            select(CuentaCliente)
            .where(CuentaCliente.correo == correo_normalizado)
            .with_for_update()
        )
        hash_guardado = cuenta.contrasena_hash if cuenta is not None else None

        if cuenta is None or not cuenta.esta_activa or hash_guardado is None:
            verificar_contrasena(contrasena, HASH_DUMMY_CONTRASENA)
            db.rollback()
            return None

        if not verificar_contrasena(contrasena, hash_guardado):
            db.rollback()
            return None

        instante = ahora or datetime.now(UTC)
        token = generar_token_sesion()
        sesion = SesionCliente(
            cuenta_cliente_id=cuenta.id,
            token_hash=hash_token_sesion(token),
            creada_en=instante,
            expira_en=instante + timedelta(minutes=duracion_minutos),
            revocada_en=None,
        )
        db.add(sesion)
        db.commit()
        db.refresh(sesion)
    except SQLAlchemyError:
        db.rollback()
        raise

    return ResultadoSesionCliente(sesion=sesion, token=token)


def obtener_cuenta_cliente_por_token(
    db: Session,
    *,
    token: str,
    ahora: datetime | None = None,
) -> CuentaCliente | None:
    """Resuelve una cuenta desde una sesion cliente vigente y no revocada."""

    instante = ahora or datetime.now(UTC)
    sesion = db.scalar(
        select(SesionCliente).where(
            SesionCliente.token_hash == hash_token_sesion(token)
        )
    )
    if (
        sesion is None
        or sesion.revocada_en is not None
        or sesion.expira_en <= instante
    ):
        return None

    cuenta = db.get(CuentaCliente, sesion.cuenta_cliente_id)
    if cuenta is None or not cuenta.esta_activa:
        return None
    return cuenta


def revocar_sesion_cliente_actual(
    db: Session,
    *,
    token: str,
    ahora: datetime | None = None,
) -> None:
    """Revoca solo la sesion cliente nombrada por la cookie actual."""

    instante = ahora or datetime.now(UTC)
    try:
        sesion = db.scalar(
            select(SesionCliente)
            .where(SesionCliente.token_hash == hash_token_sesion(token))
            .with_for_update()
        )
        if sesion is None or sesion.revocada_en is not None:
            db.rollback()
            return

        sesion.revocada_en = instante
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise


__all__ = [
    "ResultadoSesionCliente",
    "crear_sesion_cliente",
    "obtener_cuenta_cliente_por_token",
    "revocar_sesion_cliente_actual",
]
