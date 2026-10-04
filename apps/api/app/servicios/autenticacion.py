"""Autenticación por rol y creación transaccional de sesiones."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import RolUsuario, Sesion, Usuario
from app.seguridad.contrasenas import (
    HASH_DUMMY_CONTRASENA,
    verificar_contrasena,
)
from app.seguridad.correos import normalizar_correo
from app.seguridad.sesiones import generar_token_sesion, hash_token_sesion


@dataclass(frozen=True, slots=True)
class ResultadoSesionAdmin:
    """Sesión persistida y token efímero que solo se entrega mediante cookie."""

    sesion: Sesion
    token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ResultadoSesionUsuario:
    """Sesión de cualquier rol admitido y token efímero para la cookie."""

    sesion: Sesion
    rol: RolUsuario
    token: str = field(repr=False)


def _cuenta_admin_utilizable(usuario: Usuario) -> bool:
    """Indica si el estado persistido permite validar un login de ADMIN."""

    return (
        usuario.rol == RolUsuario.ADMIN.value
        and usuario.esta_activo
        and usuario.correo_verificado
        and not usuario.debe_cambiar_contrasena
        and usuario.contrasena_hash is not None
    )


def _cuenta_usuario_utilizable(usuario: Usuario) -> bool:
    """Indica si el estado persistido permite iniciar una sesión."""

    return (
        usuario.rol in {rol.value for rol in RolUsuario}
        and usuario.esta_activo
        and usuario.correo_verificado
        and not usuario.debe_cambiar_contrasena
        and usuario.contrasena_hash is not None
    )


def _autenticar_usuario(
    db: Session,
    *,
    correo: str,
    contrasena: str,
    correo_normalizado: str | None = None,
    rol_requerido: RolUsuario | None = None,
    bloquear_fila: bool = False,
) -> Usuario | None:
    """Devuelve la cuenta elegible tras validar su contraseña."""

    identidad_correo = (
        normalizar_correo(correo) if correo_normalizado is None else correo_normalizado
    )
    consulta = select(Usuario).where(Usuario.correo == identidad_correo)
    if bloquear_fila:
        consulta = consulta.with_for_update()
    usuario = db.scalar(consulta)
    contrasena_hash = usuario.contrasena_hash if usuario is not None else None

    if (
        usuario is None
        or contrasena_hash is None
        or not _cuenta_usuario_utilizable(usuario)
        or (rol_requerido is not None and usuario.rol != rol_requerido.value)
    ):
        # Mantenemos un costo similar cuando la cuenta no puede autenticarse.
        verificar_contrasena(contrasena, HASH_DUMMY_CONTRASENA)
        return None

    if not verificar_contrasena(contrasena, contrasena_hash):
        return None
    return usuario


def autenticar_admin(
    db: Session,
    *,
    correo: str,
    contrasena: str,
    correo_normalizado: str | None = None,
) -> bool:
    """Valida credenciales y estado sin modificar al usuario ni crear sesiones."""

    return (
        _autenticar_usuario(
            db,
            correo=correo,
            contrasena=contrasena,
            correo_normalizado=correo_normalizado,
            rol_requerido=RolUsuario.ADMIN,
        )
        is not None
    )


def crear_sesion_admin(
    db: Session,
    *,
    correo: str,
    contrasena: str,
    correo_normalizado: str,
    duracion_minutos: int,
    ahora: datetime | None = None,
) -> ResultadoSesionAdmin | None:
    """Autentica un ADMIN y persiste una sesión antes de exponer su cookie.

    La única copia del token original queda en memoria hasta que la ruta lo
    coloca en una cookie HttpOnly; PostgreSQL recibe solamente su hash.
    """

    if not autenticar_admin(
        db,
        correo=correo,
        contrasena=contrasena,
        correo_normalizado=correo_normalizado,
    ):
        return None

    ahora_utc = ahora or datetime.now(UTC)
    expira_en = ahora_utc + timedelta(minutes=duracion_minutos)
    token = generar_token_sesion()

    try:
        usuario = db.scalar(select(Usuario).where(Usuario.correo == correo_normalizado))
        if usuario is None:
            return None

        sesion = Sesion(
            usuario_id=usuario.id,
            token_hash=hash_token_sesion(token),
            expira_en=expira_en,
            revocado_en=None,
            creado_en=ahora_utc,
        )
        db.add(sesion)
        db.commit()
        db.refresh(sesion)
    except SQLAlchemyError:
        db.rollback()
        raise

    return ResultadoSesionAdmin(sesion=sesion, token=token)


def crear_sesion_usuario(
    db: Session,
    *,
    correo: str,
    contrasena: str,
    correo_normalizado: str,
    duracion_minutos: int,
    ahora: datetime | None = None,
) -> ResultadoSesionUsuario | None:
    """Autentica ADMIN u OPERADOR y persiste una sesión común."""

    usuario = _autenticar_usuario(
        db,
        correo=correo,
        contrasena=contrasena,
        correo_normalizado=correo_normalizado,
        bloquear_fila=True,
    )
    if usuario is None:
        db.rollback()
        return None

    ahora_utc = ahora or datetime.now(UTC)
    token = generar_token_sesion()
    sesion = Sesion(
        usuario_id=usuario.id,
        token_hash=hash_token_sesion(token),
        expira_en=ahora_utc + timedelta(minutes=duracion_minutos),
        revocado_en=None,
        creado_en=ahora_utc,
    )
    try:
        db.add(sesion)
        db.commit()
        db.refresh(sesion)
    except SQLAlchemyError:
        db.rollback()
        raise

    return ResultadoSesionUsuario(
        sesion=sesion,
        rol=RolUsuario(usuario.rol),
        token=token,
    )


def obtener_usuario_por_token(
    db: Session,
    *,
    token: str,
    ahora: datetime | None = None,
) -> Usuario | None:
    """Obtiene cualquier usuario elegible desde una sesión vigente."""

    ahora_utc = ahora or datetime.now(UTC)
    sesion = db.scalar(
        select(Sesion).where(Sesion.token_hash == hash_token_sesion(token))
    )
    if (
        sesion is None
        or sesion.revocado_en is not None
        or sesion.expira_en <= ahora_utc
    ):
        return None

    usuario = db.get(Usuario, sesion.usuario_id)
    if usuario is None or not _cuenta_usuario_utilizable(usuario):
        return None
    return usuario


def obtener_usuario_admin_por_token(
    db: Session,
    *,
    token: str,
    ahora: datetime | None = None,
) -> Usuario | None:
    """Obtiene el ADMIN si el token representa una sesión todavía válida."""

    ahora_utc = ahora or datetime.now(UTC)
    sesion = db.scalar(
        select(Sesion).where(Sesion.token_hash == hash_token_sesion(token))
    )
    if (
        sesion is None
        or sesion.revocado_en is not None
        or sesion.expira_en <= ahora_utc
    ):
        return None

    usuario = db.get(Usuario, sesion.usuario_id)
    if usuario is None or not _cuenta_admin_utilizable(usuario):
        return None

    return usuario


def revocar_sesion_actual(
    db: Session,
    *,
    token: str,
    ahora: datetime | None = None,
) -> None:
    """Revoca solamente la sesión representada por el token actual.

    Una sesión ausente, revocada o expirada ya no tiene acceso válido y se
    considera un cierre idempotente. Solo una sesión vigente requiere una
    escritura persistida antes de responder como cerrada.
    """

    ahora_utc = ahora or datetime.now(UTC)
    try:
        sesion = db.scalar(
            select(Sesion).where(Sesion.token_hash == hash_token_sesion(token))
        )
        if (
            sesion is None
            or sesion.revocado_en is not None
            or sesion.expira_en <= ahora_utc
        ):
            return

        sesion.revocado_en = ahora_utc
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise


def revocar_sesiones_vigentes(
    db: Session,
    *,
    usuario_id: int,
    ahora: datetime | None = None,
) -> int:
    """Revoca las sesiones vigentes de un ADMIN dentro de la transaccion actual.

    La funcion no hace ``commit`` ni ``rollback``: quien la invoca conserva la
    atomicidad de la operacion que cambia el estado de la cuenta.
    """

    ahora_utc = ahora or datetime.now(UTC)
    resultado = db.execute(
        update(Sesion)
        .where(
            Sesion.usuario_id == usuario_id,
            Sesion.revocado_en.is_(None),
            Sesion.expira_en > ahora_utc,
        )
        .values(revocado_en=ahora_utc)
    )
    return int(getattr(resultado, "rowcount", 0) or 0)


def revocar_sesiones_usuario(
    db: Session,
    *,
    usuario_id: int,
    ahora: datetime | None = None,
) -> int:
    """Marca toda sesion no revocada sin eliminar el historial persistido."""

    ahora_utc = ahora or datetime.now(UTC)
    resultado = db.execute(
        update(Sesion)
        .where(
            Sesion.usuario_id == usuario_id,
            Sesion.revocado_en.is_(None),
        )
        .values(revocado_en=ahora_utc)
    )
    return int(getattr(resultado, "rowcount", 0) or 0)


__all__ = [
    "ResultadoSesionAdmin",
    "ResultadoSesionUsuario",
    "autenticar_admin",
    "crear_sesion_admin",
    "crear_sesion_usuario",
    "obtener_usuario_admin_por_token",
    "obtener_usuario_por_token",
    "revocar_sesion_actual",
    "revocar_sesiones_vigentes",
    "revocar_sesiones_usuario",
]
