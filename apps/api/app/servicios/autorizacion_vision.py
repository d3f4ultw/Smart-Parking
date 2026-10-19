"""Controla la autorizacion Vision ligada a la sesion actual del OWNER."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CuentaPropietario, RolUsuario, Sesion, Usuario
from app.seguridad.contrasenas import HASH_DUMMY_CONTRASENA, verificar_contrasena
from app.seguridad.sesiones import hash_token_sesion


class VisionAutorizacionInvalidaError(ValueError):
    """La reautenticacion administrativa no se pudo completar."""


@dataclass(frozen=True, slots=True)
class EstadoAutorizacionVision:
    authorized: bool


def autorizar_sesion_vision(
    db: Session,
    *,
    usuario_id: int,
    token_sesion: str,
    contrasena_admin: str,
    ahora: datetime | None = None,
) -> None:
    """Verifica la clave administrativa y autoriza la sesion actual."""

    instante = ahora or datetime.now(UTC)
    hash_sesion = hash_token_sesion(token_sesion)
    with db.begin():
        usuario = db.scalar(
            select(Usuario).where(Usuario.id == usuario_id).with_for_update()
        )
        sesion = db.scalar(
            select(Sesion)
            .where(
                Sesion.usuario_id == usuario_id,
                Sesion.token_hash == hash_sesion,
                Sesion.revocado_en.is_(None),
                Sesion.expira_en > instante,
            )
            .with_for_update()
        )
        cuenta = db.scalar(
            select(CuentaPropietario)
            .where(CuentaPropietario.usuario_id == usuario_id)
            .with_for_update()
        )
        hash_admin = (
            cuenta.contrasena_admin_hash
            if cuenta is not None and usuario is not None
            else None
        )
        credencial_valida = verificar_contrasena(
            contrasena_admin,
            hash_admin or HASH_DUMMY_CONTRASENA,
        )
        if (
            usuario is None
            or usuario.rol != RolUsuario.OWNER.value
            or not usuario.esta_activo
            or not usuario.correo_verificado
            or usuario.debe_cambiar_contrasena
            or sesion is None
            or hash_admin is None
            or not credencial_valida
        ):
            raise VisionAutorizacionInvalidaError

        sesion.vision_autorizada = True


def obtener_estado_autorizacion_vision(
    db: Session,
    *,
    usuario_id: int,
    token_sesion: str,
    ahora: datetime | None = None,
) -> EstadoAutorizacionVision:
    """Devuelve si la sesion vigente conserva autorizacion Vision."""

    instante = ahora or datetime.now(UTC)
    sesion = db.execute(
        select(Sesion.vision_autorizada)
        .join(Usuario, Usuario.id == Sesion.usuario_id)
        .join(CuentaPropietario, CuentaPropietario.usuario_id == Usuario.id)
        .where(
            Sesion.usuario_id == usuario_id,
            Sesion.token_hash == hash_token_sesion(token_sesion),
            Sesion.revocado_en.is_(None),
            Sesion.expira_en > instante,
            Usuario.rol == RolUsuario.OWNER.value,
            Usuario.esta_activo.is_(True),
            Usuario.correo_verificado.is_(True),
            Usuario.debe_cambiar_contrasena.is_(False),
            CuentaPropietario.contrasena_admin_hash.is_not(None),
        )
    ).scalar_one_or_none()
    return EstadoAutorizacionVision(authorized=sesion is True)


def revocar_autorizacion_vision(
    db: Session,
    *,
    usuario_id: int,
    token_sesion: str,
) -> None:
    """Retira la autorizacion de Vision sin cerrar la sesion OWNER."""

    sesion = db.scalar(
        select(Sesion)
        .where(
            Sesion.usuario_id == usuario_id,
            Sesion.token_hash == hash_token_sesion(token_sesion),
            Sesion.revocado_en.is_(None),
        )
        .with_for_update()
    )
    if sesion is not None:
        sesion.vision_autorizada = False
        db.commit()


def sesion_tiene_autorizacion_vision(
    db: Session,
    *,
    token_sesion: str,
    ahora: datetime | None = None,
) -> bool:
    """Revalida rol, cuenta, sesion y autorizacion desde la base de datos."""

    instante = ahora or datetime.now(UTC)
    resultado = db.execute(
        select(Sesion, Usuario, CuentaPropietario)
        .join(Usuario, Usuario.id == Sesion.usuario_id)
        .join(CuentaPropietario, CuentaPropietario.usuario_id == Usuario.id)
        .where(
            Sesion.token_hash == hash_token_sesion(token_sesion),
            Sesion.revocado_en.is_(None),
            Sesion.expira_en > instante,
            Sesion.vision_autorizada.is_(True),
            Usuario.rol == RolUsuario.OWNER.value,
            Usuario.esta_activo.is_(True),
            Usuario.correo_verificado.is_(True),
            Usuario.debe_cambiar_contrasena.is_(False),
            CuentaPropietario.contrasena_admin_hash.is_not(None),
        )
    ).first()
    return resultado is not None


__all__ = [
    "EstadoAutorizacionVision",
    "VisionAutorizacionInvalidaError",
    "autorizar_sesion_vision",
    "obtener_estado_autorizacion_vision",
    "revocar_autorizacion_vision",
    "sesion_tiene_autorizacion_vision",
]
