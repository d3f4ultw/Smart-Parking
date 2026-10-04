"""Bitacora transaccional y concesiones limitadas para el stream ADMIN."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.orm import Session

from app.models import (
    ConexionSSEAdmin,
    EstadoEventosOperadores,
    EventoOperador,
    Usuario,
)
from app.servicios.autenticacion import obtener_usuario_admin_por_token

TipoEventoOperador = Literal["operador.creado", "operador.actualizado"]

TIPOS_EVENTO_OPERADOR = frozenset(
    {"operador.creado", "operador.actualizado"}
)
MAXIMO_EVENTOS_RETENIDOS = 10_000
MAXIMO_EVENTOS_POR_LECTURA = 100
DIAS_RETENCION_EVENTOS = 30
MAXIMO_CONEXIONES_ADMIN = 3
MAXIMAS_APERTURAS_ADMIN = 10
VENTANA_APERTURAS = timedelta(seconds=60)
DURACION_CONCESION = timedelta(seconds=45)
EDAD_LIMPIEZA_CONCESION = timedelta(minutes=5)


class SesionAdminSSENoValidaError(ValueError):
    """Indica que la sesion persistida ya no autoriza un stream ADMIN."""


class LimiteConexionesSSEError(ValueError):
    """Indica que se alcanzo un limite de streams o aperturas ADMIN."""

    def __init__(self, reintentar_en: int) -> None:
        self.reintentar_en = max(1, reintentar_en)
        super().__init__("Se alcanzo el limite de conexiones en tiempo real.")


@dataclass(frozen=True, slots=True)
class EventoSSE:
    """Campos escalares permitidos en un evento enviado al cliente."""

    id: int
    tipo: TipoEventoOperador
    operador_id: int
    ocurrido_en: str


@dataclass(frozen=True, slots=True)
class ResultadoLoteEventosSSE:
    """Resultado de un poll corto; no conserva ORM ni sesion."""

    autorizado: bool
    marca: int
    eventos: tuple[EventoSSE, ...] = ()
    requiere_resync: bool = False


def _ahora_utc(ahora: datetime | None = None) -> datetime:
    if ahora is None:
        return datetime.now(UTC)
    if ahora.tzinfo is None or ahora.utcoffset() is None:
        raise ValueError("La fecha debe incluir zona horaria.")
    return ahora.astimezone(UTC)


def registrar_evento_operador(
    db: Session,
    operador_id: int,
    tipo: TipoEventoOperador,
) -> EventoOperador:
    """Inserta un evento en la transaccion de la mutacion que lo origino."""

    if tipo not in TIPOS_EVENTO_OPERADOR:
        raise ValueError("El tipo de evento de OPERADOR no es valido.")

    ultimo_id = db.scalar(
        update(EstadoEventosOperadores)
        .where(EstadoEventosOperadores.id == 1)
        .values(ultimo_id=EstadoEventosOperadores.ultimo_id + 1)
        .returning(EstadoEventosOperadores.ultimo_id)
    )
    if ultimo_id is None:
        raise RuntimeError("No existe la fila singleton de eventos OPERADOR.")

    evento = EventoOperador(
        id=ultimo_id,
        operador_id=operador_id,
        tipo=tipo,
    )
    db.add(evento)
    db.flush()

    # La primera depuracion usa el indice temporal; el limite por cantidad
    # elimina solo el exceso mas antiguo despues de retirar la fila nueva.
    db.execute(
        delete(EventoOperador).where(
            EventoOperador.id != ultimo_id,
            EventoOperador.ocurrido_en
            < func.now() - text(f"interval '{DIAS_RETENCION_EVENTOS} days'"),
        )
    )
    cantidad = db.scalar(select(func.count()).select_from(EventoOperador)) or 0
    exceso = max(0, cantidad - MAXIMO_EVENTOS_RETENIDOS)
    if exceso:
        ids_antiguos = db.scalars(
            select(EventoOperador.id)
            .where(EventoOperador.id != ultimo_id)
            .order_by(EventoOperador.ocurrido_en, EventoOperador.id)
            .limit(exceso)
        ).all()
        if ids_antiguos:
            db.execute(
                delete(EventoOperador).where(EventoOperador.id.in_(ids_antiguos))
            )

    return evento


def obtener_marca_eventos(db: Session) -> tuple[int, int | None]:
    """Devuelve el high-water mark y el id mas antiguo aun reproducible."""

    estado = db.get(EstadoEventosOperadores, 1)
    if estado is None:
        raise RuntimeError("No existe la fila singleton de eventos OPERADOR.")
    primero = db.scalar(select(func.min(EventoOperador.id)))
    return estado.ultimo_id, primero


def cursor_necesita_resync(
    cursor: int,
    marca: int,
    primer_evento: int | None,
) -> bool:
    """Detecta si el cursor quedo antes del historial que sigue disponible."""

    if cursor >= marca:
        return False
    if primer_evento is None:
        return True
    return cursor < primer_evento - 1


def admitir_conexion_sse_admin(
    db: Session,
    *,
    admin_usuario_id: int,
    token_sesion: str,
    ahora: datetime | None = None,
) -> UUID:
    """Revalida y reserva una concesion bajo bloqueo por ADMIN."""

    ahora_utc = _ahora_utc(ahora)
    if db.in_transaction():
        db.rollback()

    with db.begin():
        admin = obtener_usuario_admin_por_token(
            db,
            token=token_sesion,
            ahora=ahora_utc,
        )
        if admin is None or admin.id != admin_usuario_id:
            raise SesionAdminSSENoValidaError

        admin_bloqueado = db.scalar(
            select(Usuario)
            .where(Usuario.id == admin_usuario_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if admin_bloqueado is None:
            raise SesionAdminSSENoValidaError

        # Se repite la validacion despues del lock para serializar cambios de
        # elegibilidad de la cuenta y aperturas concurrentes del mismo ADMIN.
        db.expire_all()
        admin = obtener_usuario_admin_por_token(
            db,
            token=token_sesion,
            ahora=ahora_utc,
        )
        if admin is None or admin.id != admin_usuario_id:
            raise SesionAdminSSENoValidaError

        filtro_admin = ConexionSSEAdmin.admin_usuario_id == admin_usuario_id
        limite_limpieza = ahora_utc - EDAD_LIMPIEZA_CONCESION
        db.execute(
            delete(ConexionSSEAdmin).where(
                filtro_admin,
                or_(
                    and_(
                        ConexionSSEAdmin.cerrada_en.is_not(None),
                        ConexionSSEAdmin.cerrada_en < limite_limpieza,
                    ),
                    and_(
                        ConexionSSEAdmin.cerrada_en.is_(None),
                        ConexionSSEAdmin.expira_en < limite_limpieza,
                    ),
                )
            )
        )

        filtro_activa = and_(
            filtro_admin,
            ConexionSSEAdmin.cerrada_en.is_(None),
            ConexionSSEAdmin.expira_en > ahora_utc,
        )
        conexiones_activas = db.scalar(
            select(func.count()).select_from(ConexionSSEAdmin).where(filtro_activa)
        ) or 0
        expiracion_mas_cercana = db.scalar(
            select(func.min(ConexionSSEAdmin.expira_en)).where(filtro_activa)
        )

        aperturas = db.scalars(
            select(ConexionSSEAdmin.abierta_en)
            .where(
                filtro_admin,
                ConexionSSEAdmin.abierta_en >= ahora_utc - VENTANA_APERTURAS,
            )
            .order_by(ConexionSSEAdmin.abierta_en)
            .limit(MAXIMAS_APERTURAS_ADMIN)
        ).all()

        reintentar_en = 0
        if conexiones_activas >= MAXIMO_CONEXIONES_ADMIN:
            if expiracion_mas_cercana is None:
                reintentar_en = 1
            else:
                reintentar_en = max(
                    1,
                    ceil((expiracion_mas_cercana - ahora_utc).total_seconds()),
                )
        if len(aperturas) >= MAXIMAS_APERTURAS_ADMIN:
            espera_por_aperturas = max(
                1,
                ceil(
                    (
                        aperturas[0]
                        + VENTANA_APERTURAS
                        - ahora_utc
                    ).total_seconds()
                ),
            )
            reintentar_en = max(reintentar_en, espera_por_aperturas)
        if reintentar_en:
            raise LimiteConexionesSSEError(reintentar_en)

        lease_id = uuid4()
        db.add(
            ConexionSSEAdmin(
                id=lease_id,
                admin_usuario_id=admin_usuario_id,
                abierta_en=ahora_utc,
                expira_en=ahora_utc + DURACION_CONCESION,
            )
        )
        db.flush()

    return lease_id


def cerrar_conexion_sse_admin(
    db: Session,
    *,
    admin_usuario_id: int,
    lease_id: UUID,
    ahora: datetime | None = None,
) -> None:
    """Marca la concesion cerrada en una transaccion breve e independiente."""

    ahora_utc = _ahora_utc(ahora)
    if db.in_transaction():
        db.rollback()
    with db.begin():
        db.execute(
            update(ConexionSSEAdmin)
            .where(
                ConexionSSEAdmin.id == lease_id,
                ConexionSSEAdmin.admin_usuario_id == admin_usuario_id,
                ConexionSSEAdmin.cerrada_en.is_(None),
            )
            .values(cerrada_en=ahora_utc)
        )


def consultar_lote_eventos_sse(
    db: Session,
    *,
    admin_usuario_id: int,
    token_sesion: str,
    lease_id: UUID,
    cursor: int,
    revalidar_sesion: bool,
    renovar_conexion: bool,
    ahora: datetime | None = None,
) -> ResultadoLoteEventosSSE:
    """Revalida, renueva y materializa hasta 100 eventos en una sesion corta."""

    ahora_utc = _ahora_utc(ahora)
    with db.begin():
        lease = db.scalar(
            select(ConexionSSEAdmin)
            .where(
                ConexionSSEAdmin.id == lease_id,
                ConexionSSEAdmin.admin_usuario_id == admin_usuario_id,
                ConexionSSEAdmin.cerrada_en.is_(None),
            )
            .with_for_update()
        )
        if lease is None or lease.expira_en <= ahora_utc:
            return ResultadoLoteEventosSSE(autorizado=False, marca=cursor)

        if revalidar_sesion:
            admin = obtener_usuario_admin_por_token(
                db,
                token=token_sesion,
                ahora=ahora_utc,
            )
            if admin is None or admin.id != admin_usuario_id:
                lease.cerrada_en = ahora_utc
                return ResultadoLoteEventosSSE(autorizado=False, marca=cursor)

        if renovar_conexion:
            lease.expira_en = ahora_utc + DURACION_CONCESION

        marca, primer_evento = obtener_marca_eventos(db)
        if cursor_necesita_resync(cursor, marca, primer_evento):
            return ResultadoLoteEventosSSE(
                autorizado=True,
                marca=marca,
                requiere_resync=True,
            )

        filas = db.scalars(
            select(EventoOperador)
            .where(EventoOperador.id > cursor)
            .order_by(EventoOperador.id)
            .limit(MAXIMO_EVENTOS_POR_LECTURA)
        ).all()
        eventos = tuple(
            EventoSSE(
                id=fila.id,
                tipo=cast(TipoEventoOperador, fila.tipo),
                operador_id=fila.operador_id,
                ocurrido_en=fila.ocurrido_en.isoformat(),
            )
            for fila in filas
        )
        return ResultadoLoteEventosSSE(
            autorizado=True,
            marca=marca,
            eventos=eventos,
        )


__all__ = [
    "DIAS_RETENCION_EVENTOS",
    "DURACION_CONCESION",
    "EDAD_LIMPIEZA_CONCESION",
    "EventoSSE",
    "LimiteConexionesSSEError",
    "MAXIMAS_APERTURAS_ADMIN",
    "MAXIMO_CONEXIONES_ADMIN",
    "MAXIMO_EVENTOS_POR_LECTURA",
    "MAXIMO_EVENTOS_RETENIDOS",
    "ResultadoLoteEventosSSE",
    "SesionAdminSSENoValidaError",
    "TipoEventoOperador",
    "admitir_conexion_sse_admin",
    "cerrar_conexion_sse_admin",
    "consultar_lote_eventos_sse",
    "cursor_necesita_resync",
    "obtener_marca_eventos",
    "registrar_evento_operador",
]
