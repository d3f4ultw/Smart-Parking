"""Inscripcion, verificacion y activacion segura de OWNER."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Literal

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    CuentaPropietario,
    DesvinculacionPropietario,
    InscripcionPropietario,
    RolUsuario,
    Usuario,
)
from app.seguridad.activaciones import generar_token_activacion, hash_token_activacion
from app.seguridad.contrasenas import (
    ContrasenaInvalidaError,
    ContrasenasNoCoincidenError,
    crear_hash_contrasena,
    validar_confirmacion_contrasena,
    verificar_contrasena,
)
from app.seguridad.correos import normalizar_correo
from app.servicios.autenticacion import revocar_sesiones_usuario

VIGENCIA_ENLACE_MINUTOS = 15
VIGENCIA_PROCESO_MINUTOS = 60
COOLDOWN_REENVIO_SEGUNDOS = 5 * 60
MAXIMO_REENVIO = 3


class InscripcionPropietarioNoDisponible(ValueError):
    """Indica que el estado ya no permite continuar con la inscripcion."""


class InscripcionPropietarioYaEnCurso(ValueError):
    """Indica que un alta vigente requiere usar la accion de reenvio."""


class ReenvioPropietarioEnEspera(ValueError):
    """Indica cuanto debe esperar antes de volver a enviar el enlace."""

    def __init__(self, segundos_restantes: int) -> None:
        self.segundos_restantes = segundos_restantes
        super().__init__(
            "El enlace de OWNER todavía está dentro del periodo de espera."
        )


class LimiteReenviosPropietario(ValueError):
    """Indica que se agotaron los reenvios permitidos del proceso vigente."""


class ContrasenasPropietarioIgualesError(ContrasenaInvalidaError):
    """Indica que las credenciales de acceso y administración deben diferir."""


class DatosInscripcionPropietarioInvalidosError(ValueError):
    """Indica que faltan datos de identidad requeridos para el alta."""


@dataclass(frozen=True, slots=True)
class ResultadoDesafioPropietario:
    """Desafio efimero que solo se entrega mediante cookie HttpOnly."""

    token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class DatosDesafioPropietario:
    """Describe una cuenta elegible sin exponer su correo ni credenciales."""

    tipo_cuenta: Literal["nueva", "retorno"] | None
    nombre: str | None = None
    apellido_paterno: str | None = None
    apellido_materno: str | None = None
    expira_en: datetime | None = None


@dataclass(frozen=True, slots=True)
class EstadoInscripcionPropietario:
    """Estado consultable sin exponer hashes ni tokens del proceso."""

    id: int
    correo: str = field(repr=False)
    estado: Literal["pendiente", "bloqueado", "expirado", "completado"]
    correo_inicial_enviado: bool
    expira_en: datetime
    proceso_expira_en: datetime
    enlace_vigente: bool
    segundos_proceso: int
    reenviados_usados: int
    reenviados_restantes: int
    proximo_reenvio_en: datetime | None
    segundos_cooldown: int
    reenvio_bloqueado: bool
    motivo_bloqueo: str | None


def existe_owner_activo(db: Session) -> bool:
    """Consulta el estado de OWNER sin dejar abierta una transaccion de lectura."""

    try:
        existe = _hay_owner_activo(db)
        db.rollback()
        return existe
    except SQLAlchemyError:
        db.rollback()
        raise


def listar_estados_inscripciones_propietario(
    db: Session,
    *,
    ahora: datetime | None = None,
) -> tuple[EstadoInscripcionPropietario, ...]:
    """Consulta estados sin devolver credenciales ni dejar una lectura abierta."""

    ahora_utc = _ahora_utc(ahora)
    try:
        inscripciones = db.scalars(
            select(InscripcionPropietario).order_by(
                InscripcionPropietario.proceso_expira_en.asc(),
                InscripcionPropietario.correo.asc(),
            )
        ).all()
        owner_activo = _hay_owner_activo(db)
        estados = tuple(
            _crear_estado_inscripcion(inscripcion, ahora_utc, owner_activo)
            for inscripcion in inscripciones
        )
        db.rollback()
        return estados
    except SQLAlchemyError:
        db.rollback()
        raise


def _crear_estado_inscripcion(
    inscripcion: InscripcionPropietario,
    ahora: datetime,
    owner_activo: bool,
) -> EstadoInscripcionPropietario:
    expira_en = _normalizar_fecha_utc(inscripcion.expira_en)
    proceso_expira_en = _normalizar_fecha_utc(inscripcion.proceso_expira_en)
    ultimo_envio_en = _normalizar_fecha_utc(inscripcion.ultimo_envio_en)
    proximo_envio = ultimo_envio_en + timedelta(seconds=COOLDOWN_REENVIO_SEGUNDOS)
    segundos_cooldown = max(0, ceil((proximo_envio - ahora).total_seconds()))
    segundos_proceso = max(0, ceil((proceso_expira_en - ahora).total_seconds()))

    if inscripcion.consumido_en is not None:
        estado: Literal["pendiente", "bloqueado", "expirado", "completado"] = (
            "completado"
        )
        motivo = "El proceso ya se completó."
    elif proceso_expira_en <= ahora:
        estado = "expirado"
        motivo = "La ventana de inscripción de 60 minutos terminó."
    elif owner_activo:
        estado = "bloqueado"
        motivo = "Ya existe una cuenta de dueño activa."
    elif inscripcion.reenviados >= MAXIMO_REENVIO:
        estado = "bloqueado"
        motivo = "Se agotaron los 3 reenvíos; espera al fin de la ventana."
    elif proximo_envio >= proceso_expira_en:
        estado = "bloqueado"
        motivo = "El cooldown termina después de la ventana de inscripción."
    else:
        estado = "pendiente"
        motivo = (
            "El reenvío está en espera del periodo de cooldown."
            if segundos_cooldown > 0
            else "El enlace caducó; se puede solicitar otro."
            if expira_en <= ahora
            else None
        )

    reenvio_bloqueado = estado != "pendiente" or segundos_cooldown > 0
    return EstadoInscripcionPropietario(
        id=inscripcion.id,
        correo=inscripcion.correo,
        estado=estado,
        correo_inicial_enviado=True,
        expira_en=expira_en,
        proceso_expira_en=proceso_expira_en,
        enlace_vigente=expira_en > ahora and proceso_expira_en > ahora,
        segundos_proceso=segundos_proceso,
        reenviados_usados=inscripcion.reenviados,
        reenviados_restantes=max(0, MAXIMO_REENVIO - inscripcion.reenviados),
        proximo_reenvio_en=(
            proximo_envio if estado == "pendiente" and segundos_cooldown > 0 else None
        ),
        segundos_cooldown=segundos_cooldown,
        reenvio_bloqueado=reenvio_bloqueado,
        motivo_bloqueo=motivo,
    )


def _normalizar_fecha_utc(fecha: datetime) -> datetime:
    if fecha.tzinfo is None or fecha.utcoffset() is None:
        return fecha.replace(tzinfo=UTC)
    return fecha.astimezone(UTC)


def _hay_owner_activo(db: Session) -> bool:
    return (
        db.scalar(
            select(Usuario.id)
            .where(
                Usuario.rol == RolUsuario.OWNER.value,
                Usuario.esta_activo.is_(True),
            )
            .limit(1)
        )
        is not None
    )


def _ahora_utc(ahora: datetime | None) -> datetime:
    if ahora is None:
        return datetime.now(UTC)
    if ahora.tzinfo is None or ahora.utcoffset() is None:
        raise ValueError("La fecha de inscripcion debe incluir zona horaria.")
    return ahora.astimezone(UTC)


def _bloquear_correo(db: Session, correo: str) -> None:
    """Serializa procesos simultaneos del mismo correo sin guardar su hash."""

    huella = hashlib.sha256(f"owner:{correo}".encode()).digest()[:8]
    clave = int.from_bytes(huella, byteorder="big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:clave)"), {"clave": clave})


def _bloquear_altas_propietario(db: Session) -> None:
    """Serializa altas nuevas para conservar un unico proceso vigente."""

    huella = hashlib.sha256(b"owner:inscripciones-nuevas").digest()[:8]
    clave = int.from_bytes(huella, byteorder="big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:clave)"), {"clave": clave})


def _normalizar_nombre(
    valor: str | None,
    *,
    obligatorio: bool,
) -> str | None:
    """Normaliza un campo existente de identidad y conserva sus límites."""

    if valor is None:
        if obligatorio:
            raise DatosInscripcionPropietarioInvalidosError
        return None
    nombre = " ".join(valor.split())
    if not nombre:
        if obligatorio:
            raise DatosInscripcionPropietarioInvalidosError
        return None
    if len(nombre) > 100 or not nombre.isprintable():
        raise DatosInscripcionPropietarioInvalidosError
    return nombre


def _cuenta_existente_elegible(db: Session, usuario: Usuario) -> bool:
    """Acepta solo el retorno de una cuenta OWNER que quedo sin rol."""

    if (
        usuario.rol is not None
        or not usuario.esta_activo
        or not usuario.correo_verificado
        or usuario.debe_cambiar_contrasena
        or usuario.contrasena_hash is None
    ):
        return False

    cuenta = db.scalar(
        select(CuentaPropietario).where(
            CuentaPropietario.usuario_id == usuario.id
        )
    )
    if (
        cuenta is None
        or cuenta.contrasena_admin_hash is not None
        or cuenta.rol_anterior is not None
    ):
        return False

    desvinculacion_confirmada = db.scalar(
        select(DesvinculacionPropietario.id)
        .where(
            DesvinculacionPropietario.usuario_id == usuario.id,
            DesvinculacionPropietario.cuenta_propietario_id == cuenta.id,
            DesvinculacionPropietario.consumida_en.is_not(None),
            DesvinculacionPropietario.invalidada_en.is_(None),
        )
        .limit(1)
    )
    return desvinculacion_confirmada is not None


def iniciar_inscripcion_propietario(
    db: Session,
    *,
    correo: str,
    entregar_enlace: Callable[[str, str], None],
    modo: Literal["automatico", "nueva", "reenvio"] = "automatico",
    ahora: datetime | None = None,
) -> None:
    """Entrega o reenvia un enlace sin asignar privilegios antes de confirmarlo."""

    correo_normalizado = normalizar_correo(correo)
    ahora_utc = _ahora_utc(ahora)
    token = generar_token_activacion()
    try:
        db.rollback()
        with db.begin():
            if modo == "nueva":
                _bloquear_altas_propietario(db)
            _bloquear_correo(db, correo_normalizado)
            if ahora is None:
                ahora_utc = datetime.now(UTC)

            if modo == "nueva":
                inscripcion_en_curso = db.scalar(
                    select(InscripcionPropietario.id)
                    .where(
                        InscripcionPropietario.consumido_en.is_(None),
                        InscripcionPropietario.proceso_expira_en > ahora_utc,
                    )
                    .order_by(InscripcionPropietario.id.asc())
                    .with_for_update()
                    .limit(1)
                )
                if inscripcion_en_curso is not None:
                    raise InscripcionPropietarioYaEnCurso

            owner_activo = db.scalar(
                select(Usuario.id)
                .where(
                    Usuario.rol == RolUsuario.OWNER.value,
                    Usuario.esta_activo.is_(True),
                )
                .limit(1)
            )
            if owner_activo is not None:
                raise InscripcionPropietarioNoDisponible

            usuario = db.scalar(
                select(Usuario)
                .where(Usuario.correo == correo_normalizado)
                .with_for_update()
            )
            if usuario is not None and not _cuenta_existente_elegible(db, usuario):
                raise InscripcionPropietarioNoDisponible

            inscripcion = db.scalar(
                select(InscripcionPropietario)
                .where(InscripcionPropietario.correo == correo_normalizado)
                .with_for_update()
            )
            proceso_vigente = (
                inscripcion is not None
                and inscripcion.consumido_en is None
                and inscripcion.proceso_expira_en > ahora_utc
            )
            if modo == "nueva" and proceso_vigente:
                raise InscripcionPropietarioYaEnCurso
            if modo == "reenvio" and not proceso_vigente:
                raise InscripcionPropietarioNoDisponible
            if proceso_vigente:
                assert inscripcion is not None
                espera = (
                    inscripcion.ultimo_envio_en
                    + timedelta(seconds=COOLDOWN_REENVIO_SEGUNDOS)
                    - ahora_utc
                )
                if espera.total_seconds() > 0:
                    raise ReenvioPropietarioEnEspera(
                        max(1, int(espera.total_seconds() + 0.999))
                    )
                if inscripcion.reenviados >= MAXIMO_REENVIO:
                    raise LimiteReenviosPropietario
                reenvios = inscripcion.reenviados + 1
            else:
                reenvios = 0

            if proceso_vigente:
                assert inscripcion is not None
                proceso_expira_en = _normalizar_fecha_utc(inscripcion.proceso_expira_en)
            else:
                proceso_expira_en = ahora_utc + timedelta(
                    minutes=VIGENCIA_PROCESO_MINUTOS
                )
            enlace_expira_en = min(
                ahora_utc + timedelta(minutes=VIGENCIA_ENLACE_MINUTOS),
                proceso_expira_en,
            )

            if inscripcion is None:
                inscripcion = InscripcionPropietario(
                    correo=correo_normalizado,
                    token_hash=hash_token_activacion(token),
                    expira_en=enlace_expira_en,
                    proceso_expira_en=proceso_expira_en,
                    ultimo_envio_en=ahora_utc,
                    reenviados=reenvios,
                )
                db.add(inscripcion)
            else:
                inscripcion.token_hash = hash_token_activacion(token)
                inscripcion.desafio_hash = None
                inscripcion.desafio_expira_en = None
                inscripcion.canjeado_en = None
                inscripcion.consumido_en = None
                inscripcion.expira_en = enlace_expira_en
                inscripcion.proceso_expira_en = proceso_expira_en
                inscripcion.ultimo_envio_en = ahora_utc
                inscripcion.reenviados = reenvios

            inscripcion.usuario_id = usuario.id if usuario is not None else None
            inscripcion.rol_anterior = usuario.rol if usuario is not None else None
            db.flush()
            # La entrega ocurre antes del commit; si SMTP falla, el enlace previo
            # conserva su vigencia y el contador no avanza.
            entregar_enlace(correo_normalizado, token)
    except (
        InscripcionPropietarioNoDisponible,
        InscripcionPropietarioYaEnCurso,
        ReenvioPropietarioEnEspera,
        LimiteReenviosPropietario,
    ):
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise
    finally:
        del token


def canjear_enlace_propietario(
    db: Session,
    *,
    token: str,
    duracion_desafio_minutos: int,
    ahora: datetime | None = None,
) -> ResultadoDesafioPropietario:
    """Valida el enlace y lo cambia por un desafio corto con hash."""

    if not 5 <= duracion_desafio_minutos <= 60:
        raise ValueError("La vigencia del desafio no es valida.")
    hash_token = hash_token_activacion(token)
    ahora_utc = _ahora_utc(ahora)
    token_desafio = generar_token_activacion()
    try:
        db.rollback()
        with db.begin():
            inscripcion = db.scalar(
                select(InscripcionPropietario)
                .where(InscripcionPropietario.token_hash == hash_token)
                .with_for_update()
            )
            if (
                inscripcion is None
                or inscripcion.consumido_en is not None
                or inscripcion.expira_en <= ahora_utc
                or inscripcion.proceso_expira_en <= ahora_utc
                or _hay_owner_activo(db)
            ):
                raise InscripcionPropietarioNoDisponible

            fin_desafio = min(
                ahora_utc + timedelta(minutes=duracion_desafio_minutos),
                _normalizar_fecha_utc(inscripcion.expira_en),
                _normalizar_fecha_utc(inscripcion.proceso_expira_en),
            )
            if fin_desafio <= ahora_utc:
                raise InscripcionPropietarioNoDisponible
            inscripcion.desafio_hash = hash_token_activacion(token_desafio)
            inscripcion.desafio_expira_en = fin_desafio
            inscripcion.canjeado_en = ahora_utc
    except InscripcionPropietarioNoDisponible:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise

    return ResultadoDesafioPropietario(token=token_desafio)


def obtener_datos_desafio_propietario(
    db: Session,
    *,
    token_desafio: str | None,
    ahora: datetime | None = None,
) -> DatosDesafioPropietario:
    """Devuelve la cuenta elegible y su nombre, solo durante el desafio."""

    if not token_desafio:
        db.rollback()
        return DatosDesafioPropietario(tipo_cuenta=None)
    hash_desafio = hash_token_activacion(token_desafio)
    ahora_utc = _ahora_utc(ahora)
    try:
        inscripcion = db.scalar(
            select(InscripcionPropietario).where(
                InscripcionPropietario.desafio_hash == hash_desafio
            )
        )
        if (
            inscripcion is None
            or inscripcion.consumido_en is not None
            or inscripcion.desafio_expira_en is None
            or inscripcion.desafio_expira_en <= ahora_utc
            or _hay_owner_activo(db)
        ):
            db.rollback()
            return DatosDesafioPropietario(tipo_cuenta=None)
        if inscripcion.usuario_id is None:
            usuario = db.scalar(
                select(Usuario.id).where(Usuario.correo == inscripcion.correo)
            )
            if usuario is not None:
                db.rollback()
                return DatosDesafioPropietario(tipo_cuenta=None)
            resultado = DatosDesafioPropietario(
                tipo_cuenta="nueva",
                expira_en=_normalizar_fecha_utc(inscripcion.desafio_expira_en),
            )
        else:
            usuario = db.get(Usuario, inscripcion.usuario_id)
            if (
                usuario is None
                or usuario.rol != inscripcion.rol_anterior
                or not _cuenta_existente_elegible(db, usuario)
            ):
                db.rollback()
                return DatosDesafioPropietario(tipo_cuenta=None)
            resultado = DatosDesafioPropietario(
                tipo_cuenta="retorno",
                nombre=usuario.nombre,
                apellido_paterno=usuario.apellido_paterno,
                apellido_materno=usuario.apellido_materno,
                expira_en=_normalizar_fecha_utc(inscripcion.desafio_expira_en),
            )
        db.rollback()
        return resultado
    except SQLAlchemyError:
        db.rollback()
        raise


def obtener_tipo_cuenta_desafio(
    db: Session,
    *,
    token_desafio: str | None,
    ahora: datetime | None = None,
) -> Literal["nueva", "retorno"] | None:
    """Devuelve solo la clasificacion para consumidores sin datos de perfil."""

    return obtener_datos_desafio_propietario(
        db,
        token_desafio=token_desafio,
        ahora=ahora,
    ).tipo_cuenta


def completar_inscripcion_propietario(
    db: Session,
    *,
    token_desafio: str | None,
    contrasena_admin: str,
    confirmar_contrasena_admin: str | None = None,
    contrasena_login: str | None = None,
    confirmar_contrasena_login: str | None = None,
    nombre: str | None = None,
    apellido_paterno: str | None = None,
    apellido_materno: str | None = None,
    ahora: datetime | None = None,
) -> None:
    """Activa OWNER y sus credenciales en una sola transaccion."""

    if not token_desafio:
        db.rollback()
        raise InscripcionPropietarioNoDisponible
    try:
        if confirmar_contrasena_admin is None:
            raise ContrasenaInvalidaError(
                "La confirmación de la contraseña administrativa es obligatoria."
            )
        validar_confirmacion_contrasena(
            contrasena_admin,
            confirmar_contrasena_admin,
        )
        if contrasena_login is not None:
            if confirmar_contrasena_login is None:
                raise ContrasenaInvalidaError(
                    "La confirmación de la contraseña de acceso es obligatoria."
                )
            validar_confirmacion_contrasena(
                contrasena_login,
                confirmar_contrasena_login,
            )
            if contrasena_login == contrasena_admin:
                raise ContrasenasPropietarioIgualesError(
                    "Las contraseñas de acceso y administración deben ser distintas."
                )
        elif confirmar_contrasena_login is not None:
            raise ContrasenaInvalidaError(
                "La contraseña de acceso no corresponde a esta cuenta."
            )
        nombre_normalizado = _normalizar_nombre(nombre, obligatorio=True)
        apellido_paterno_normalizado = _normalizar_nombre(
            apellido_paterno,
            obligatorio=True,
        )
        apellido_materno_normalizado = _normalizar_nombre(
            apellido_materno,
            obligatorio=False,
        )
    except ContrasenasNoCoincidenError as error:
        db.rollback()
        raise ContrasenaInvalidaError(str(error)) from None
    except DatosInscripcionPropietarioInvalidosError:
        db.rollback()
        raise

    hash_desafio = hash_token_activacion(token_desafio)
    ahora_utc = _ahora_utc(ahora)
    try:
        db.rollback()
        with db.begin():
            inscripcion = db.scalar(
                select(InscripcionPropietario)
                .where(InscripcionPropietario.desafio_hash == hash_desafio)
                .with_for_update()
            )
            ahora_commit = datetime.now(UTC) if ahora is None else ahora_utc
            if (
                inscripcion is None
                or inscripcion.consumido_en is not None
                or inscripcion.canjeado_en is None
                or inscripcion.desafio_expira_en is None
                or inscripcion.desafio_expira_en <= ahora_commit
            ):
                raise InscripcionPropietarioNoDisponible
            if (
                db.scalar(
                    select(Usuario.id)
                    .where(
                        Usuario.rol == RolUsuario.OWNER.value,
                        Usuario.esta_activo.is_(True),
                    )
                    .limit(1)
                )
                is not None
            ):
                raise InscripcionPropietarioNoDisponible

            contrasena_admin_hash = crear_hash_contrasena(contrasena_admin)
            if inscripcion.usuario_id is None:
                if contrasena_login is None:
                    raise ContrasenaInvalidaError(
                        "La contraseña de acceso es obligatoria para una cuenta nueva."
                    )
                usuario_existente = db.scalar(
                    select(Usuario.id)
                    .where(Usuario.correo == inscripcion.correo)
                    .with_for_update()
                )
                if usuario_existente is not None:
                    raise InscripcionPropietarioNoDisponible
                contrasena_login_hash = crear_hash_contrasena(contrasena_login)
                usuario = Usuario(
                    nombre=nombre_normalizado,
                    apellido_paterno=apellido_paterno_normalizado,
                    apellido_materno=apellido_materno_normalizado,
                    correo=inscripcion.correo,
                    contrasena_hash=contrasena_login_hash,
                    rol=RolUsuario.OWNER.value,
                    correo_verificado=True,
                    debe_cambiar_contrasena=False,
                    esta_activo=True,
                )
                db.add(usuario)
                db.flush()
            else:
                if (
                    contrasena_login is not None
                    or confirmar_contrasena_login is not None
                ):
                    raise ContrasenaInvalidaError(
                        "La contraseña de acceso existente no se modifica "
                        "durante el retorno."
                    )
                usuario = db.scalar(
                    select(Usuario)
                    .where(Usuario.id == inscripcion.usuario_id)
                    .with_for_update()
                )
                if (
                    usuario is None
                    or usuario.correo != inscripcion.correo
                    or usuario.rol != inscripcion.rol_anterior
                    or not _cuenta_existente_elegible(db, usuario)
                ):
                    raise InscripcionPropietarioNoDisponible
                cuenta_propietario = db.scalar(
                    select(CuentaPropietario)
                    .where(CuentaPropietario.usuario_id == usuario.id)
                    .with_for_update()
                )
                if cuenta_propietario is None:
                    raise InscripcionPropietarioNoDisponible
                if (
                    usuario.contrasena_hash is None
                    or verificar_contrasena(
                        contrasena_admin,
                        usuario.contrasena_hash,
                    )
                ):
                    raise ContrasenasPropietarioIgualesError(
                        "La contraseña administrativa debe ser distinta a "
                        "la contraseña de acceso."
                    )
                usuario.nombre = nombre_normalizado
                usuario.apellido_paterno = apellido_paterno_normalizado
                usuario.apellido_materno = apellido_materno_normalizado
                cuenta_propietario.contrasena_admin_hash = contrasena_admin_hash
                # El rol previo nulo conserva el fallback roleless del primer enlace.
                cuenta_propietario.rol_anterior = None
                usuario.rol = RolUsuario.OWNER.value

            if inscripcion.usuario_id is None:
                db.add(
                    CuentaPropietario(
                        usuario_id=usuario.id,
                        contrasena_admin_hash=contrasena_admin_hash,
                        rol_anterior=None,
                    )
                )
            inscripcion.consumido_en = ahora_commit
            inscripcion.desafio_hash = None
            inscripcion.desafio_expira_en = None
            revocar_sesiones_usuario(db, usuario_id=usuario.id, ahora=ahora_commit)
    except (
        InscripcionPropietarioNoDisponible,
        ContrasenaInvalidaError,
        DatosInscripcionPropietarioInvalidosError,
    ):
        db.rollback()
        raise
    except IntegrityError:
        # Incluye correo duplicado y la carrera protegida por el indice parcial.
        db.rollback()
        raise InscripcionPropietarioNoDisponible from None
    except SQLAlchemyError:
        db.rollback()
        raise


__all__ = [
    "COOLDOWN_REENVIO_SEGUNDOS",
    "DatosDesafioPropietario",
    "DatosInscripcionPropietarioInvalidosError",
    "EstadoInscripcionPropietario",
    "MAXIMO_REENVIO",
    "VIGENCIA_ENLACE_MINUTOS",
    "VIGENCIA_PROCESO_MINUTOS",
    "ContrasenasPropietarioIgualesError",
    "InscripcionPropietarioNoDisponible",
    "InscripcionPropietarioYaEnCurso",
    "LimiteReenviosPropietario",
    "ReenvioPropietarioEnEspera",
    "ResultadoDesafioPropietario",
    "canjear_enlace_propietario",
    "completar_inscripcion_propietario",
    "existe_owner_activo",
    "iniciar_inscripcion_propietario",
    "listar_estados_inscripciones_propietario",
    "obtener_datos_desafio_propietario",
    "obtener_tipo_cuenta_desafio",
]
