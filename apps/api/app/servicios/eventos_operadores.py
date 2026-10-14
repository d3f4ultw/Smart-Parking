"""Journal transaccional y concesiones SSE para usuarios autenticados."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.orm import Session

from app.models import (
    ConexionSSEUsuario,
    EstadoEventosTiempoReal,
    EventoTiempoReal,
    Usuario,
)
from app.servicios.autenticacion import obtener_usuario_por_token

TipoEventoOperador = Literal["operador.creado", "operador.actualizado"]
TipoEventoTiempoReal = Literal[
    "operador.creado",
    "operador.actualizado",
    "cajon.actualizado",
]

TIPOS_EVENTO_OPERADOR = frozenset({"operador.creado", "operador.actualizado"})
TIPOS_EVENTO_CAJON = frozenset({"cajon.actualizado"})
TIPOS_EVENTO_TIEMPO_REAL = TIPOS_EVENTO_OPERADOR | TIPOS_EVENTO_CAJON
EVENTOS_POR_ROL: dict[str, frozenset[str]] = {
    "OPERADOR": TIPOS_EVENTO_CAJON,
    "OWNER": TIPOS_EVENTO_TIEMPO_REAL,
}
ROLES_STREAM = frozenset(EVENTOS_POR_ROL)
MAXIMO_EVENTOS_RETENIDOS = 10_000
MAXIMO_EVENTOS_POR_LECTURA = 100
DIAS_RETENCION_EVENTOS = 30
MAXIMO_CONEXIONES_SSE = 6
MAXIMAS_APERTURAS_SSE = 10
VENTANA_APERTURAS = timedelta(seconds=60)
DURACION_CONCESION = timedelta(seconds=45)
EDAD_LIMPIEZA_CONCESION = timedelta(minutes=5)


class SesionTiempoRealNoValidaError(ValueError):
    """Indica que la sesion persistida no autoriza un stream."""


class LimiteConexionesSSEError(ValueError):
    """Indica que se alcanzo un limite de streams o aperturas por usuario."""

    def __init__(self, reintentar_en: int) -> None:
        self.reintentar_en = max(1, reintentar_en)
        super().__init__("Se alcanzo el limite de conexiones en tiempo real.")


@dataclass(frozen=True, slots=True)
class EventoSSE:
    """Campos escalares permitidos en un evento enviado al cliente."""

    id: int
    tipo: TipoEventoTiempoReal
    recurso_tipo: str
    recurso_id: int
    ocurrido_en: str
    datos: dict[str, object] | None = None

    @property
    def operador_id(self) -> int:
        """Mantiene legibles los consumidores de eventos actuales de operador."""

        return self.recurso_id


@dataclass(frozen=True, slots=True)
class ResultadoLoteEventosSSE:
    """Resultado de un poll corto; no conserva ORM ni sesion."""

    autorizado: bool
    marca: int
    eventos: tuple[EventoSSE, ...] = ()
    requiere_resync: bool = False
    cursor_escaneado: int = 0


def _ahora_utc(ahora: datetime | None = None) -> datetime:
    if ahora is None:
        return datetime.now(UTC)
    if ahora.tzinfo is None or ahora.utcoffset() is None:
        raise ValueError("La fecha debe incluir zona horaria.")
    return ahora.astimezone(UTC)


def tipos_autorizados_para_rol(rol: str) -> frozenset[str]:
    """Devuelve los tipos permitidos; un rol desconocido deniega por defecto."""

    return EVENTOS_POR_ROL.get(rol, frozenset())


def registrar_evento_tiempo_real(
    db: Session,
    *,
    recurso_tipo: str,
    recurso_id: int,
    tipo: TipoEventoTiempoReal,
    datos: dict[str, object] | None = None,
) -> EventoTiempoReal:
    """Asigna el cursor global dentro de la transaccion de la mutacion."""

    combinacion_operador = (
        recurso_tipo == "operador" and tipo in TIPOS_EVENTO_OPERADOR and datos is None
    )
    combinacion_cajon = (
        recurso_tipo == "cajon" and tipo == "cajon.actualizado" and datos is not None
    )
    if recurso_id <= 0 or not (combinacion_operador or combinacion_cajon):
        raise ValueError("El evento de tiempo real no es valido.")

    ultimo_id = db.scalar(
        update(EstadoEventosTiempoReal)
        .where(EstadoEventosTiempoReal.id == 1)
        .values(ultimo_id=EstadoEventosTiempoReal.ultimo_id + 1)
        .returning(EstadoEventosTiempoReal.ultimo_id)
    )
    if ultimo_id is None:
        raise RuntimeError("No existe la fila singleton del journal en tiempo real.")

    evento = EventoTiempoReal(
        id=ultimo_id,
        recurso_tipo=recurso_tipo,
        recurso_id=recurso_id,
        tipo=tipo,
        datos=dict(datos) if datos is not None else None,
    )
    db.add(evento)
    db.flush()

    db.execute(
        delete(EventoTiempoReal).where(
            EventoTiempoReal.id != ultimo_id,
            EventoTiempoReal.ocurrido_en
            < func.now() - text(f"interval '{DIAS_RETENCION_EVENTOS} days'"),
        )
    )
    cantidad = db.scalar(select(func.count()).select_from(EventoTiempoReal)) or 0
    exceso = max(0, cantidad - MAXIMO_EVENTOS_RETENIDOS)
    if exceso:
        ids_antiguos = db.scalars(
            select(EventoTiempoReal.id)
            .where(EventoTiempoReal.id != ultimo_id)
            .order_by(EventoTiempoReal.ocurrido_en, EventoTiempoReal.id)
            .limit(exceso)
        ).all()
        if ids_antiguos:
            db.execute(
                delete(EventoTiempoReal).where(EventoTiempoReal.id.in_(ids_antiguos))
            )

    return evento


def registrar_evento_operador(
    db: Session,
    operador_id: int,
    tipo: TipoEventoOperador,
) -> EventoTiempoReal:
    """Registra una notificacion de OPERADOR en el journal compartido."""

    return registrar_evento_tiempo_real(
        db,
        recurso_tipo="operador",
        recurso_id=operador_id,
        tipo=tipo,
    )


def registrar_evento_cajon(
    db: Session,
    cajon_id: int,
    datos: dict[str, object],
) -> EventoTiempoReal:
    """Registra una instantanea de cajon en la misma transaccion de estado."""

    return registrar_evento_tiempo_real(
        db,
        recurso_tipo="cajon",
        recurso_id=cajon_id,
        tipo="cajon.actualizado",
        datos=datos,
    )


def obtener_marca_eventos(db: Session) -> tuple[int, int | None]:
    """Devuelve el high-water y el evento retenido mas antiguo global."""

    estado = db.get(EstadoEventosTiempoReal, 1)
    if estado is None:
        raise RuntimeError("No existe la fila singleton del journal en tiempo real.")
    primero = db.scalar(select(func.min(EventoTiempoReal.id)))
    return estado.ultimo_id, primero


def cursor_necesita_resync(
    cursor: int,
    marca: int,
    primer_evento: int | None,
) -> bool:
    """Detecta si el cursor quedo antes del historial retenido."""

    if cursor >= marca:
        return False
    if primer_evento is None:
        return True
    return cursor < primer_evento - 1


def admitir_conexion_sse(
    db: Session,
    *,
    usuario_id: int,
    token_sesion: str,
    ahora: datetime | None = None,
) -> UUID:
    """Revalida una sesion y reserva una concesion por usuario autenticado."""

    ahora_utc = _ahora_utc(ahora)
    if db.in_transaction():
        db.rollback()

    with db.begin():
        usuario = obtener_usuario_por_token(db, token=token_sesion, ahora=ahora_utc)
        if (
            usuario is None
            or usuario.id != usuario_id
            or usuario.rol not in ROLES_STREAM
        ):
            raise SesionTiempoRealNoValidaError

        usuario_bloqueado = db.scalar(
            select(Usuario)
            .where(Usuario.id == usuario_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if usuario_bloqueado is None:
            raise SesionTiempoRealNoValidaError

        db.expire_all()
        usuario = obtener_usuario_por_token(db, token=token_sesion, ahora=ahora_utc)
        if (
            usuario is None
            or usuario.id != usuario_id
            or usuario.rol not in ROLES_STREAM
        ):
            raise SesionTiempoRealNoValidaError

        filtro_usuario = ConexionSSEUsuario.usuario_id == usuario_id
        limite_limpieza = ahora_utc - EDAD_LIMPIEZA_CONCESION
        db.execute(
            delete(ConexionSSEUsuario).where(
                filtro_usuario,
                or_(
                    and_(
                        ConexionSSEUsuario.cerrada_en.is_not(None),
                        ConexionSSEUsuario.cerrada_en < limite_limpieza,
                    ),
                    and_(
                        ConexionSSEUsuario.cerrada_en.is_(None),
                        ConexionSSEUsuario.expira_en < limite_limpieza,
                    ),
                ),
            )
        )

        filtro_activa = and_(
            filtro_usuario,
            ConexionSSEUsuario.cerrada_en.is_(None),
            ConexionSSEUsuario.expira_en > ahora_utc,
        )
        conexiones_activas = (
            db.scalar(
                select(func.count())
                .select_from(ConexionSSEUsuario)
                .where(filtro_activa)
            )
            or 0
        )
        expiracion_mas_cercana = db.scalar(
            select(func.min(ConexionSSEUsuario.expira_en)).where(filtro_activa)
        )
        aperturas = db.scalars(
            select(ConexionSSEUsuario.abierta_en)
            .where(
                filtro_usuario,
                ConexionSSEUsuario.abierta_en >= ahora_utc - VENTANA_APERTURAS,
            )
            .order_by(ConexionSSEUsuario.abierta_en)
            .limit(MAXIMAS_APERTURAS_SSE)
        ).all()

        reintentar_en = 0
        if conexiones_activas >= MAXIMO_CONEXIONES_SSE:
            reintentar_en = max(
                1,
                ceil((expiracion_mas_cercana - ahora_utc).total_seconds())
                if expiracion_mas_cercana is not None
                else 1,
            )
        if len(aperturas) >= MAXIMAS_APERTURAS_SSE:
            espera_por_aperturas = max(
                1,
                ceil((aperturas[0] + VENTANA_APERTURAS - ahora_utc).total_seconds()),
            )
            reintentar_en = max(reintentar_en, espera_por_aperturas)
        if reintentar_en:
            raise LimiteConexionesSSEError(reintentar_en)

        lease_id = uuid4()
        db.add(
            ConexionSSEUsuario(
                id=lease_id,
                usuario_id=usuario_id,
                abierta_en=ahora_utc,
                expira_en=ahora_utc + DURACION_CONCESION,
            )
        )
        db.flush()

    return lease_id


def cerrar_conexion_sse(
    db: Session,
    *,
    usuario_id: int,
    lease_id: UUID,
    ahora: datetime | None = None,
) -> None:
    """Marca una concesion cerrada en una transaccion breve."""

    ahora_utc = _ahora_utc(ahora)
    if db.in_transaction():
        db.rollback()
    with db.begin():
        db.execute(
            update(ConexionSSEUsuario)
            .where(
                ConexionSSEUsuario.id == lease_id,
                ConexionSSEUsuario.usuario_id == usuario_id,
                ConexionSSEUsuario.cerrada_en.is_(None),
            )
            .values(cerrada_en=ahora_utc)
        )


def consultar_lote_eventos_usuario(
    db: Session,
    *,
    usuario_id: int,
    rol_usuario: str,
    token_sesion: str,
    lease_id: UUID,
    cursor: int,
    revalidar_sesion: bool,
    renovar_conexion: bool,
    ahora: datetime | None = None,
) -> ResultadoLoteEventosSSE:
    """Revalida, renueva y materializa hasta 100 eventos autorizados."""

    ahora_utc = _ahora_utc(ahora)
    with db.begin():
        lease = db.scalar(
            select(ConexionSSEUsuario)
            .where(
                ConexionSSEUsuario.id == lease_id,
                ConexionSSEUsuario.usuario_id == usuario_id,
                ConexionSSEUsuario.cerrada_en.is_(None),
            )
            .with_for_update()
        )
        if lease is None or lease.expira_en <= ahora_utc:
            return ResultadoLoteEventosSSE(
                autorizado=False,
                marca=cursor,
                cursor_escaneado=cursor,
            )

        rol_actual = rol_usuario
        if revalidar_sesion:
            usuario = obtener_usuario_por_token(db, token=token_sesion, ahora=ahora_utc)
            if (
                usuario is None
                or usuario.id != usuario_id
                or usuario.rol not in ROLES_STREAM
                or usuario.rol != rol_usuario
            ):
                lease.cerrada_en = ahora_utc
                return ResultadoLoteEventosSSE(
                    autorizado=False,
                    marca=cursor,
                    cursor_escaneado=cursor,
                )
            rol_actual = usuario.rol

        if renovar_conexion:
            lease.expira_en = ahora_utc + DURACION_CONCESION

        tipos_autorizados = tipos_autorizados_para_rol(rol_actual)
        marca, primer_evento = obtener_marca_eventos(db)
        if tipos_autorizados and cursor_necesita_resync(
            cursor,
            marca,
            primer_evento,
        ):
            return ResultadoLoteEventosSSE(
                autorizado=True,
                marca=marca,
                requiere_resync=True,
                cursor_escaneado=marca,
            )

        if not tipos_autorizados:
            return ResultadoLoteEventosSSE(
                autorizado=True,
                marca=marca,
                cursor_escaneado=marca,
            )

        filas = db.scalars(
            select(EventoTiempoReal)
            .where(
                EventoTiempoReal.id > cursor,
                EventoTiempoReal.tipo.in_(tipos_autorizados),
            )
            .order_by(EventoTiempoReal.id)
            .limit(MAXIMO_EVENTOS_POR_LECTURA)
        ).all()
        eventos = tuple(
            EventoSSE(
                id=fila.id,
                tipo=cast(TipoEventoTiempoReal, fila.tipo),
                recurso_tipo=fila.recurso_tipo,
                recurso_id=fila.recurso_id,
                ocurrido_en=fila.ocurrido_en.isoformat(),
                datos=fila.datos,
            )
            for fila in filas
        )
        cursor_escaneado = (
            filas[-1].id if len(filas) == MAXIMO_EVENTOS_POR_LECTURA else marca
        )
        return ResultadoLoteEventosSSE(
            autorizado=True,
            marca=marca,
            eventos=eventos,
            cursor_escaneado=cursor_escaneado,
        )


__all__ = [
    "DIAS_RETENCION_EVENTOS",
    "DURACION_CONCESION",
    "EDAD_LIMPIEZA_CONCESION",
    "EVENTOS_POR_ROL",
    "EventoSSE",
    "LimiteConexionesSSEError",
    "MAXIMAS_APERTURAS_SSE",
    "MAXIMO_CONEXIONES_SSE",
    "MAXIMO_EVENTOS_POR_LECTURA",
    "MAXIMO_EVENTOS_RETENIDOS",
    "ResultadoLoteEventosSSE",
    "ROLES_STREAM",
    "SesionTiempoRealNoValidaError",
    "TIPOS_EVENTO_TIEMPO_REAL",
    "TIPOS_EVENTO_CAJON",
    "TIPOS_EVENTO_OPERADOR",
    "TipoEventoTiempoReal",
    "TipoEventoOperador",
    "admitir_conexion_sse",
    "cerrar_conexion_sse",
    "consultar_lote_eventos_usuario",
    "cursor_necesita_resync",
    "obtener_marca_eventos",
    "registrar_evento_operador",
    "registrar_evento_cajon",
    "registrar_evento_tiempo_real",
    "tipos_autorizados_para_rol",
]
