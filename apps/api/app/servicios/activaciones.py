"""Servicio transaccional para generar activaciones de cuenta."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Literal, NoReturn

from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import ActivacionCuenta, RolUsuario, Usuario
from app.seguridad.activaciones import (
    generar_codigo_verificacion,
    generar_token_activacion,
    hash_codigo_verificacion,
    hash_token_activacion,
)
from app.seguridad.contrasenas import (
    HASH_DUMMY_CODIGO,
    HASH_DUMMY_CONTRASENA,
    ContrasenaInvalidaError,
    crear_hash_contrasena,
    generar_contrasena_temporal,
    validar_confirmacion_contrasena,
    verificar_contrasena,
)
from app.seguridad.correos import normalizar_correo

MINUTOS_VIGENCIA_ACTIVACION = 15
ModoActivacion = Literal["manual", "temporal"]


class ErrorActivacion(ValueError):
    """Clase base para errores esperados del servicio de activaciones."""


class UsuarioNoEncontradoError(ErrorActivacion):
    """Se lanza cuando se solicita una activacion para un usuario inexistente."""

    def __init__(self) -> None:
        super().__init__("El usuario no existe.")


class ActivacionPendienteExistenteError(ErrorActivacion):
    """Evita crear activaciones pendientes ilimitadas para el mismo usuario."""

    def __init__(self) -> None:
        super().__init__("El usuario ya tiene una activacion pendiente.")


class ErrorCreacionActivacion(ErrorActivacion):
    """Se lanza cuando la activacion no pudo persistirse."""

    def __init__(self) -> None:
        super().__init__("No fue posible crear la activacion.")


class ErrorReenvioActivacion(ErrorActivacion):
    """Se lanza cuando el reenvio no pudo persistirse de forma atomica."""

    def __init__(self) -> None:
        super().__init__("No fue posible reenviar la activacion.")


class CooldownReenvioError(ErrorActivacion):
    """Indica que el reenvio aun esta dentro del cooldown vigente."""

    def __init__(self, segundos_restantes: int) -> None:
        self.segundos_restantes = max(1, segundos_restantes)
        super().__init__("El reenvio de activacion aun esta en cooldown.")


class ActivacionNoDisponible(ErrorActivacion):
    """Indica que una activacion no puede consumirse de forma segura."""

    def __init__(self) -> None:
        super().__init__("Activacion no disponible")


class DatosActivacionInvalidos(ErrorActivacion):
    """Indica que las credenciales no coinciden con la activacion usable."""

    def __init__(self) -> None:
        super().__init__("Datos de activacion invalidos")


@dataclass(frozen=True, slots=True)
class ResultadoActivacion:
    """Activacion persistida y credenciales efimeras para el correo.

    Los secretos no aparecen en el ``repr`` para evitar filtraciones accidentales
    en trazas o mensajes de diagnostico.
    """

    activacion: ActivacionCuenta
    token: str = field(repr=False)
    codigo: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ResultadoReenvioActivacion:
    """Credenciales efimeras creadas para enviar un reenvio."""

    usuario: Usuario
    activacion: ActivacionCuenta
    token: str = field(repr=False)
    codigo: str = field(repr=False)
    contrasena_temporal: str | None = field(default=None, repr=False)


def _ahora_utc(ahora: datetime | None) -> datetime:
    if ahora is None:
        return datetime.now(UTC)
    if ahora.tzinfo is None or ahora.utcoffset() is None:
        raise ValueError("La fecha de activacion debe incluir zona horaria.")
    return ahora.astimezone(UTC)


def _obtener_activacion_y_usuario_bloqueados(
    db: Session,
    *,
    token: str,
    al_rechazar: Callable[[], NoReturn],
) -> tuple[ActivacionCuenta, Usuario]:
    """Obtiene y bloquea la activacion y su usuario en la transaccion actual."""

    activacion = db.scalar(
        select(ActivacionCuenta)
        .where(ActivacionCuenta.token_hash == hash_token_activacion(token))
        .with_for_update()
    )
    if activacion is None:
        al_rechazar()

    usuario = db.scalar(
        select(Usuario).where(Usuario.id == activacion.usuario_id).with_for_update()
    )
    if usuario is None:
        al_rechazar()

    return activacion, usuario


def _validar_estado_activacion(
    activacion: ActivacionCuenta,
    usuario: Usuario,
    *,
    ahora_utc: datetime,
    modo_esperado: ModoActivacion | None = None,
    al_rechazar: Callable[[], NoReturn],
) -> ModoActivacion:
    """Valida el estado comun y determina el modo desde el usuario."""

    if (
        usuario.rol != RolUsuario.ADMIN.value
        or activacion.consumido_en is not None
        or activacion.expira_en <= ahora_utc
        or not usuario.esta_activo
        or usuario.correo_verificado
        or usuario.contrasena_hash is None
        or activacion.codigo_hash is None
    ):
        al_rechazar()

    modo = "temporal" if usuario.debe_cambiar_contrasena else "manual"
    if modo_esperado is not None and modo != modo_esperado:
        al_rechazar()
    return modo


def _rechazar_manual(codigo: str) -> NoReturn:
    """Aproxima el trabajo criptografico antes de rechazar una activacion manual."""

    verificar_contrasena(codigo, HASH_DUMMY_CODIGO)
    raise ActivacionNoDisponible


def _rechazar_temporal(
    codigo: str,
    contrasena_temporal: str,
) -> NoReturn:
    """Aproxima el trabajo criptografico antes de rechazar una activacion temporal."""

    verificar_contrasena(codigo, HASH_DUMMY_CODIGO)
    verificar_contrasena(contrasena_temporal, HASH_DUMMY_CONTRASENA)
    raise ActivacionNoDisponible


def crear_activacion(
    db: Session,
    usuario_id: int,
    *,
    ahora: datetime | None = None,
) -> ResultadoActivacion:
    """Crea una activacion pendiente dentro de una transaccion propia.

    El token y el codigo se mantienen unicamente en memoria; en PostgreSQL se
    almacenan sus representaciones derivadas seguras.
    """

    ahora_utc = _ahora_utc(ahora)
    expira_en = ahora_utc + timedelta(minutes=MINUTOS_VIGENCIA_ACTIVACION)

    try:
        with db.begin():
            usuario_existe = db.scalar(
                select(Usuario.id).where(Usuario.id == usuario_id).with_for_update()
            )
            if usuario_existe is None:
                raise UsuarioNoEncontradoError

            activacion_pendiente = db.scalar(
                select(ActivacionCuenta.id)
                .where(
                    ActivacionCuenta.usuario_id == usuario_id,
                    ActivacionCuenta.consumido_en.is_(None),
                    ActivacionCuenta.expira_en > ahora_utc,
                )
                .limit(1)
            )
            if activacion_pendiente is not None:
                raise ActivacionPendienteExistenteError

            token = generar_token_activacion()
            codigo = generar_codigo_verificacion()
            activacion = ActivacionCuenta(
                usuario_id=usuario_id,
                token_hash=hash_token_activacion(token),
                codigo_hash=hash_codigo_verificacion(codigo),
                expira_en=expira_en,
                consumido_en=None,
            )
            db.add(activacion)
            db.flush()
            return ResultadoActivacion(
                activacion=activacion,
                token=token,
                codigo=codigo,
            )
    except SQLAlchemyError as error:
        db.rollback()
        raise ErrorCreacionActivacion from error


def _cooldown_reenvio_activo(
    activacion: ActivacionCuenta,
    *,
    cooldown_segundos: int,
    ahora_utc: datetime,
) -> bool:
    """Indica si la activacion mas reciente aun esta dentro del cooldown."""

    creado_en = _creado_en_utc(activacion)
    limite_cooldown = ahora_utc - timedelta(seconds=cooldown_segundos)
    return creado_en > limite_cooldown


def _creado_en_utc(activacion: ActivacionCuenta) -> datetime:
    """Normaliza la fecha persistida de una activacion a UTC."""

    creado_en = activacion.creado_en
    if creado_en.tzinfo is None or creado_en.utcoffset() is None:
        return creado_en.replace(tzinfo=UTC)
    return creado_en.astimezone(UTC)


def _segundos_cooldown_restantes(
    activacion: ActivacionCuenta,
    *,
    cooldown_segundos: int,
    ahora_utc: datetime,
) -> int:
    """Calcula el tiempo restante con redondeo conservador hacia arriba."""

    creado_en = _creado_en_utc(activacion)
    limite_cooldown = creado_en + timedelta(seconds=cooldown_segundos)
    segundos = ceil((limite_cooldown - ahora_utc).total_seconds())
    return max(1, segundos)


def reenviar_activacion(
    db: Session,
    correo: str,
    *,
    cooldown_segundos: int,
    ahora: datetime | None = None,
) -> ResultadoReenvioActivacion | None:
    """Regenera una activacion pendiente respetando cooldown y concurrencia.

    ``None`` representa los casos que deben responder de forma generica:
    cuenta inexistente, no ADMIN, inactiva o verificada. El cooldown se expone
    internamente mediante ``CooldownReenvioError`` para que la CLI pueda
    informar el tiempo restante sin cambiar la respuesta HTTP publica.
    El correo se construye y envia fuera de esta transaccion, despues del
    commit, para no mantener bloqueos durante una llamada de red.
    """

    correo_normalizado = normalizar_correo(correo)
    ahora_utc = _ahora_utc(ahora)
    expira_en = ahora_utc + timedelta(minutes=MINUTOS_VIGENCIA_ACTIVACION)

    try:
        with db.begin():
            usuario = db.scalar(
                select(Usuario)
                .where(Usuario.correo == correo_normalizado)
                .with_for_update()
            )
            if (
                usuario is None
                or usuario.rol != RolUsuario.ADMIN.value
                or usuario.correo_verificado
                or not usuario.esta_activo
            ):
                return None

            ultima_activacion = db.scalar(
                select(ActivacionCuenta)
                .where(ActivacionCuenta.usuario_id == usuario.id)
                .order_by(
                    desc(ActivacionCuenta.creado_en),
                    desc(ActivacionCuenta.id),
                )
                .limit(1)
                .with_for_update()
            )
            if ultima_activacion is not None and _cooldown_reenvio_activo(
                ultima_activacion,
                cooldown_segundos=cooldown_segundos,
                ahora_utc=ahora_utc,
            ):
                raise CooldownReenvioError(
                    _segundos_cooldown_restantes(
                        ultima_activacion,
                        cooldown_segundos=cooldown_segundos,
                        ahora_utc=ahora_utc,
                    )
                )

            activaciones_pendientes = db.scalars(
                select(ActivacionCuenta)
                .where(
                    ActivacionCuenta.usuario_id == usuario.id,
                    ActivacionCuenta.consumido_en.is_(None),
                )
                .with_for_update()
            ).all()
            for activacion_pendiente in activaciones_pendientes:
                activacion_pendiente.consumido_en = ahora_utc

            token = generar_token_activacion()
            codigo = generar_codigo_verificacion()
            contrasena_temporal: str | None = None
            if usuario.debe_cambiar_contrasena:
                contrasena_temporal = generar_contrasena_temporal()
                usuario.contrasena_hash = crear_hash_contrasena(contrasena_temporal)

            nueva_activacion = ActivacionCuenta(
                usuario_id=usuario.id,
                token_hash=hash_token_activacion(token),
                codigo_hash=hash_codigo_verificacion(codigo),
                expira_en=expira_en,
                consumido_en=None,
                creado_en=ahora_utc,
            )
            db.add(nueva_activacion)
            db.flush()
            return ResultadoReenvioActivacion(
                usuario=usuario,
                activacion=nueva_activacion,
                token=token,
                codigo=codigo,
                contrasena_temporal=contrasena_temporal,
            )
    except CooldownReenvioError:
        db.rollback()
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise ErrorReenvioActivacion from error


def prevalidar_activacion(
    db: Session,
    *,
    token: str,
    ahora: datetime | None = None,
) -> ModoActivacion:
    """Determina el modo de una activacion usable sin cambiar su estado.

    La operacion solo adquiere bloqueos de lectura para reutilizar las mismas
    condiciones que protegen el consumo final. No valida el codigo ni devuelve
    credenciales, por lo que sirve unicamente para resolver la presentacion.
    """

    ahora_controlado = _ahora_utc(ahora) if ahora is not None else None

    with db.begin():

        def rechazar() -> NoReturn:
            raise ActivacionNoDisponible

        activacion, usuario = _obtener_activacion_y_usuario_bloqueados(
            db,
            token=token,
            al_rechazar=rechazar,
        )
        ahora_utc = (
            ahora_controlado if ahora_controlado is not None else datetime.now(UTC)
        )
        return _validar_estado_activacion(
            activacion,
            usuario,
            ahora_utc=ahora_utc,
            al_rechazar=rechazar,
        )


def activar_cuenta_manual(
    db: Session,
    *,
    token: str,
    codigo: str,
    ahora: datetime | None = None,
) -> None:
    """Consume atomically una activacion valida para contrasena manual.

    La activacion y el usuario se bloquean en la misma transaccion. El valor
    ``ahora`` existe solo para pruebas con tiempo controlado; en produccion se
    toma la hora UTC despues de adquirir ambos bloqueos.
    """

    ahora_controlado = _ahora_utc(ahora) if ahora is not None else None

    with db.begin():

        def rechazar() -> NoReturn:
            _rechazar_manual(codigo)

        activacion, usuario = _obtener_activacion_y_usuario_bloqueados(
            db,
            token=token,
            al_rechazar=rechazar,
        )
        ahora_utc = (
            ahora_controlado if ahora_controlado is not None else datetime.now(UTC)
        )
        _validar_estado_activacion(
            activacion,
            usuario,
            ahora_utc=ahora_utc,
            modo_esperado="manual",
            al_rechazar=rechazar,
        )
        if activacion.codigo_hash is None or not verificar_contrasena(
            codigo,
            activacion.codigo_hash,
        ):
            raise DatosActivacionInvalidos from None

        usuario.correo_verificado = True
        activacion.consumido_en = ahora_utc


def activar_cuenta_temporal(
    db: Session,
    *,
    token: str,
    codigo: str,
    contrasena_temporal: str,
    nueva_contrasena: str,
    confirmar_contrasena: str,
    ahora: datetime | None = None,
) -> None:
    """Reemplaza la contrasena temporal y consume una activacion de ADMIN.

    El usuario y la activacion se bloquean antes de validar cualquier estado
    para que una sola solicitud pueda completar la transicion.
    """

    ahora_controlado = _ahora_utc(ahora) if ahora is not None else None

    with db.begin():

        def rechazar() -> NoReturn:
            _rechazar_temporal(codigo, contrasena_temporal)

        activacion, usuario = _obtener_activacion_y_usuario_bloqueados(
            db,
            token=token,
            al_rechazar=rechazar,
        )
        ahora_utc = (
            ahora_controlado if ahora_controlado is not None else datetime.now(UTC)
        )
        _validar_estado_activacion(
            activacion,
            usuario,
            ahora_utc=ahora_utc,
            modo_esperado="temporal",
            al_rechazar=rechazar,
        )
        if activacion.codigo_hash is None or not verificar_contrasena(
            codigo,
            activacion.codigo_hash,
        ):
            verificar_contrasena(contrasena_temporal, HASH_DUMMY_CONTRASENA)
            raise DatosActivacionInvalidos from None
        if usuario.contrasena_hash is None or not verificar_contrasena(
            contrasena_temporal,
            usuario.contrasena_hash,
        ):
            raise DatosActivacionInvalidos from None

        validar_confirmacion_contrasena(nueva_contrasena, confirmar_contrasena)
        if verificar_contrasena(nueva_contrasena, usuario.contrasena_hash):
            raise ContrasenaInvalidaError(
                "La nueva contrasena no puede ser la temporal."
            )

        usuario.contrasena_hash = crear_hash_contrasena(nueva_contrasena)
        usuario.correo_verificado = True
        usuario.debe_cambiar_contrasena = False
        activacion.consumido_en = ahora_utc
        db.flush()


__all__ = [
    "ActivacionPendienteExistenteError",
    "ActivacionNoDisponible",
    "CooldownReenvioError",
    "DatosActivacionInvalidos",
    "ErrorActivacion",
    "ErrorCreacionActivacion",
    "ErrorReenvioActivacion",
    "MINUTOS_VIGENCIA_ACTIVACION",
    "ModoActivacion",
    "ResultadoActivacion",
    "ResultadoReenvioActivacion",
    "UsuarioNoEncontradoError",
    "activar_cuenta_manual",
    "activar_cuenta_temporal",
    "crear_activacion",
    "prevalidar_activacion",
    "reenviar_activacion",
]
