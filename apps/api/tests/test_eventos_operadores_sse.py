"""Pruebas transaccionales del diario y las concesiones SSE."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Barrier, Thread
from threading import Event as EventoHilo
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.correo.errores import ErrorEnvioCorreo
from app.models import (
    ActivacionCuenta,
    ConexionSSEUsuario,
    EstadoEventosTiempoReal,
    EventoTiempoReal,
    RolUsuario,
    Sesion,
    Usuario,
)
from app.seguridad.activaciones import hash_token_activacion
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.activaciones_operador import completar_activacion_operador
from app.servicios.eventos_operadores import (
    MAXIMO_EVENTOS_POR_LECTURA,
    MAXIMO_EVENTOS_RETENIDOS,
    LimiteConexionesSSEError,
    admitir_conexion_sse,
    cerrar_conexion_sse,
    consultar_lote_eventos_usuario,
    registrar_evento_cajon,
    registrar_evento_operador,
    tipos_autorizados_para_rol,
)
from app.servicios.operadores import (
    OperadorYaActivoError,
    OperadorYaInactivoError,
    desactivar_operador,
    reactivar_operador,
    reenviar_invitacion_operador,
    regenerar_contrasena_operador,
)
from app.servicios.usuarios import crear_operador

HASH_SINTETICO = "hash-sintetico-de-prueba"


def _correo() -> str:
    return f"eventos-sse-{uuid4().hex}@example.com"


def _crear_owner(db: Session) -> tuple[int, str]:
    owner_id = db.scalar(
        select(Usuario.id).where(
            Usuario.rol == RolUsuario.OWNER.value,
            Usuario.esta_activo.is_(True),
        )
    )
    db.rollback()
    if owner_id is None:
        owner = Usuario(
            nombre="Owner",
            apellido_paterno="Prueba",
            correo=_correo(),
            contrasena_hash=HASH_SINTETICO,
            rol=RolUsuario.OWNER.value,
            correo_verificado=True,
            debe_cambiar_contrasena=False,
            esta_activo=True,
        )
        db.add(owner)
        db.flush()
        owner_id = owner.id
        db.commit()
        db.rollback()
    token = f"token-owner-{uuid4().hex}"
    db.add(
        Sesion(
            usuario_id=owner_id,
            token_hash=hash_token_sesion(token),
            expira_en=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db.commit()
    db.rollback()
    return owner_id, token


def _crear_operador(db: Session, *, pendiente: bool = False) -> Usuario:
    operador = Usuario(
        nombre="Grace",
        apellido_paterno="Hopper",
        apellido_materno="Murray",
        correo=_correo(),
        contrasena_hash=None if pendiente else HASH_SINTETICO,
        rol=RolUsuario.OPERADOR.value,
        correo_verificado=not pendiente,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(operador)
    db.commit()
    db.rollback()
    return operador


def _cantidad_eventos(db: Session, operador_id: int) -> int:
    db.rollback()
    cantidad = (
        db.scalar(
            select(func.count())
            .select_from(EventoTiempoReal)
            .where(EventoTiempoReal.operador_id == operador_id)
        )
        or 0
    )
    db.rollback()
    return cantidad


def test_journal_filtra_replay_por_rol_y_deniega_tipos_desconocidos(
    db: Session,
) -> None:
    owner_id, token_owner = _crear_owner(db)
    operador = _crear_operador(db)
    token_operador = f"token-operador-{uuid4().hex}"
    db.add(
        Sesion(
            usuario_id=operador.id,
            token_hash=hash_token_sesion(token_operador),
            expira_en=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    evento = registrar_evento_operador(db, operador.id, "operador.creado")
    db.commit()
    evento_cajon = registrar_evento_cajon(
        db,
        1,
        {
            "cajon_id": 1,
            "numero": 1,
            "estado_fisico": "OCUPADO",
            "estado_operativo": "DISPONIBLE",
            "motivo_operativo": None,
            "estado_efectivo": "OCUPADO",
            "estado_fisico_actualizado_en": "2026-10-06T12:00:00+00:00",
            "estado_operativo_actualizado_en": "2026-10-06T12:00:00+00:00",
            "actualizado_en": "2026-10-06T12:00:00+00:00",
        },
    )
    db.commit()
    lease_operador = admitir_conexion_sse(
        db,
        usuario_id=operador.id,
        token_sesion=token_operador,
    )
    lote_operador = consultar_lote_eventos_usuario(
        db,
        usuario_id=operador.id,
        rol_usuario="OPERADOR",
        token_sesion=token_operador,
        lease_id=lease_operador,
        cursor=0,
        revalidar_sesion=True,
        renovar_conexion=True,
    )
    assert lote_operador.autorizado is True
    assert [fila.id for fila in lote_operador.eventos] == [evento_cajon.id]
    assert lote_operador.eventos[0].datos is not None
    assert lote_operador.eventos[0].datos["cajon_id"] == 1
    assert lote_operador.cursor_escaneado == evento_cajon.id

    lease_owner = admitir_conexion_sse(
        db,
        usuario_id=owner_id,
        token_sesion=token_owner,
    )
    lote_owner = consultar_lote_eventos_usuario(
        db,
        usuario_id=owner_id,
        rol_usuario="OWNER",
        token_sesion=token_owner,
        lease_id=lease_owner,
        cursor=0,
        revalidar_sesion=True,
        renovar_conexion=True,
    )
    assert tipos_autorizados_para_rol("OPERADOR") == {"cajon.actualizado"}
    assert tipos_autorizados_para_rol("ROL_FALSO") == frozenset()
    assert tipos_autorizados_para_rol("ADMIN") == frozenset()
    assert [fila.id for fila in lote_owner.eventos] == [
        evento.id,
        evento_cajon.id,
    ]
    assert tipos_autorizados_para_rol("OWNER") == {
        "operador.creado",
        "operador.actualizado",
        "cajon.actualizado",
    }


def test_limite_de_seis_es_independiente_por_cuenta_y_rol(db: Session) -> None:
    owner_id, token_owner = _crear_owner(db)
    operador = _crear_operador(db)
    token_operador = f"token-operador-{uuid4().hex}"
    db.add(
        Sesion(
            usuario_id=operador.id,
            token_hash=hash_token_sesion(token_operador),
            expira_en=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db.commit()
    ahora = datetime.now(UTC)

    leases_admin = [
        admitir_conexion_sse(
            db,
            usuario_id=owner_id,
            token_sesion=token_owner,
            ahora=ahora,
        )
        for _ in range(6)
    ]
    leases_operador = [
        admitir_conexion_sse(
            db,
            usuario_id=operador.id,
            token_sesion=token_operador,
            ahora=ahora,
        )
        for _ in range(6)
    ]

    assert len(leases_admin) == len(leases_operador) == 6
    with pytest.raises(LimiteConexionesSSEError):
        admitir_conexion_sse(
            db,
            usuario_id=owner_id,
            token_sesion=token_owner,
            ahora=ahora,
        )
    with pytest.raises(LimiteConexionesSSEError):
        admitir_conexion_sse(
            db,
            usuario_id=operador.id,
            token_sesion=token_operador,
            ahora=ahora,
        )


def test_evento_y_contador_se_revierten_juntos(db: Session) -> None:
    operador = _crear_operador(db)

    with pytest.raises(RuntimeError, match="fallo controlado"):
        with db.begin():
            evento = registrar_evento_operador(
                db,
                operador.id,
                "operador.actualizado",
            )
            assert evento.id == 1
            raise RuntimeError("fallo controlado")

    db.rollback()
    estado = db.get(EstadoEventosTiempoReal, 1)
    assert estado is not None
    assert estado.ultimo_id == 0
    assert _cantidad_eventos(db, operador.id) == 0

    with db.begin():
        evento = registrar_evento_operador(db, operador.id, "operador.creado")
        assert evento.id == 1
    db.rollback()
    assert _cantidad_eventos(db, operador.id) == 1


def test_event_ids_wait_for_the_prior_transaction_commit(db: Session) -> None:
    """La prueba observa la espera real del lock de la fila singleton."""

    operador = _crear_operador(db)
    db.rollback()
    segundo_inicio = EventoHilo()
    segundo_fin = EventoHilo()
    pid_segundo: list[int] = []
    ids_segundo: list[int] = []
    errores: list[BaseException] = []
    motor = db.get_bind()
    assert isinstance(motor, Engine)

    def crear_en_segunda_transaccion() -> None:
        try:
            with Session(
                bind=motor,
                autoflush=False,
                expire_on_commit=False,
            ) as otra_db:
                with otra_db.begin():
                    pid_segundo.append(otra_db.scalar(text("SELECT pg_backend_pid()")))
                    segundo_inicio.set()
                    evento = registrar_evento_operador(
                        otra_db,
                        operador.id,
                        "operador.actualizado",
                    )
                    ids_segundo.append(evento.id)
        except BaseException as error:
            errores.append(error)
        finally:
            segundo_fin.set()

    with db.begin():
        primero = registrar_evento_operador(db, operador.id, "operador.creado")
        assert primero.id == 1
        hilo = Thread(target=crear_en_segunda_transaccion, daemon=True)
        hilo.start()
        assert segundo_inicio.wait(timeout=10)

        estado_espera: str | None = None
        vence = monotonic() + 10
        while monotonic() < vence:
            with motor.connect() as conexion:
                estado_espera = conexion.scalar(
                    text(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"
                    ),
                    {"pid": pid_segundo[0]},
                )
            if estado_espera == "Lock":
                break
            if segundo_fin.is_set():
                break
            sleep(0.02)

        assert estado_espera == "Lock"
        assert not segundo_fin.is_set()

    hilo.join(timeout=10)
    assert not hilo.is_alive()
    assert not errores
    assert ids_segundo == [2]
    db.rollback()
    assert [
        evento.id
        for evento in db.scalars(select(EventoTiempoReal).order_by(EventoTiempoReal.id))
    ] == [1, 2]


def test_dos_sesiones_owner_leen_replay_independientemente_y_paginan_cien(
    db: Session,
) -> None:
    owner_a, token_a = _crear_owner(db)
    owner_b = owner_a
    token_b = f"token-owner-{uuid4().hex}"
    db.add(
        Sesion(
            usuario_id=owner_b,
            token_hash=hash_token_sesion(token_b),
            expira_en=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db.commit()
    db.rollback()
    operador = _crear_operador(db)
    with db.begin():
        for _ in range(MAXIMO_EVENTOS_POR_LECTURA + 1):
            registrar_evento_operador(db, operador.id, "operador.actualizado")

    lease_a = admitir_conexion_sse(
        db,
        usuario_id=owner_a,
        token_sesion=token_a,
    )
    lease_b = admitir_conexion_sse(
        db,
        usuario_id=owner_b,
        token_sesion=token_b,
    )

    lote_a = consultar_lote_eventos_usuario(
        db,
        usuario_id=owner_a,
        rol_usuario="OWNER",
        token_sesion=token_a,
        lease_id=lease_a,
        cursor=0,
        revalidar_sesion=True,
        renovar_conexion=False,
    )
    lote_b = consultar_lote_eventos_usuario(
        db,
        usuario_id=owner_b,
        rol_usuario="OWNER",
        token_sesion=token_b,
        lease_id=lease_b,
        cursor=0,
        revalidar_sesion=True,
        renovar_conexion=False,
    )
    assert [evento.id for evento in lote_a.eventos] == list(
        range(1, MAXIMO_EVENTOS_POR_LECTURA + 1)
    )
    assert [evento.id for evento in lote_b.eventos] == [
        evento.id for evento in lote_a.eventos
    ]

    siguiente = consultar_lote_eventos_usuario(
        db,
        usuario_id=owner_a,
        rol_usuario="OWNER",
        token_sesion=token_a,
        lease_id=lease_a,
        cursor=lote_a.eventos[-1].id,
        revalidar_sesion=False,
        renovar_conexion=False,
    )
    assert [evento.id for evento in siguiente.eventos] == [101]
    assert lote_a.eventos[0].tipo == "operador.actualizado"
    assert lote_a.eventos[0].operador_id == operador.id
    assert datetime.fromisoformat(lote_a.eventos[0].ocurrido_en).utcoffset() is not None


def test_resync_cuando_cursor_quedo_fuera_del_historial(db: Session) -> None:
    owner_id, token_owner = _crear_owner(db)
    operador = _crear_operador(db)
    with db.begin():
        estado = db.get(EstadoEventosTiempoReal, 1)
        assert estado is not None
        estado.ultimo_id = 4
        db.add(
            EventoTiempoReal(
                id=4,
                operador_id=operador.id,
                tipo="operador.actualizado",
            )
        )

    lease_id = admitir_conexion_sse(
        db,
        usuario_id=owner_id,
        token_sesion=token_owner,
    )
    lote = consultar_lote_eventos_usuario(
        db,
        usuario_id=owner_id,
        rol_usuario="OWNER",
        token_sesion=token_owner,
        lease_id=lease_id,
        cursor=1,
        revalidar_sesion=True,
        renovar_conexion=False,
    )

    assert lote.autorizado is True
    assert lote.requiere_resync is True
    assert lote.marca == 4
    assert lote.eventos == ()


def test_retencion_expira_por_fecha_y_limita_a_diez_mil(db: Session) -> None:
    operador = _crear_operador(db)
    ahora = datetime.now(UTC)
    eventos = [
        {
            "id": identificador,
            "recurso_tipo": "operador",
            "recurso_id": operador.id,
            "tipo": "operador.actualizado",
            "ocurrido_en": ahora - timedelta(days=31 if identificador == 1 else 1),
        }
        for identificador in range(1, MAXIMO_EVENTOS_RETENIDOS + 2)
    ]
    with db.begin():
        estado = db.get(EstadoEventosTiempoReal, 1)
        assert estado is not None
        estado.ultimo_id = MAXIMO_EVENTOS_RETENIDOS + 1
        db.execute(insert(EventoTiempoReal), eventos)

    with db.begin():
        nuevo = registrar_evento_operador(db, operador.id, "operador.creado")
        assert nuevo.id == MAXIMO_EVENTOS_RETENIDOS + 2

    db.rollback()
    ids = db.scalars(select(EventoTiempoReal.id).order_by(EventoTiempoReal.id)).all()
    assert len(ids) == MAXIMO_EVENTOS_RETENIDOS
    assert ids[0] == 3
    assert ids[-1] == MAXIMO_EVENTOS_RETENIDOS + 2
    assert 1 not in ids
    assert 2 not in ids


def test_limites_de_streams_aperturas_renovacion_y_limpieza(db: Session) -> None:
    owner_id, token = _crear_owner(db)
    ahora = datetime.now(UTC)
    leases = [
        admitir_conexion_sse(
            db,
            usuario_id=owner_id,
            token_sesion=token,
            ahora=ahora + timedelta(seconds=indice),
        )
        for indice in range(6)
    ]
    with pytest.raises(LimiteConexionesSSEError) as error:
        admitir_conexion_sse(
            db,
            usuario_id=owner_id,
            token_sesion=token,
            ahora=ahora + timedelta(seconds=4),
        )
    assert error.value.reintentar_en > 0

    cerrar_conexion_sse(
        db,
        usuario_id=owner_id,
        lease_id=leases[0],
        ahora=ahora + timedelta(seconds=4),
    )
    lease_nuevo = admitir_conexion_sse(
        db,
        usuario_id=owner_id,
        token_sesion=token,
        ahora=ahora + timedelta(seconds=5),
    )
    assert lease_nuevo not in leases

    for lease_id in [*leases[1:], lease_nuevo]:
        cerrar_conexion_sse(
            db,
            usuario_id=owner_id,
            lease_id=lease_id,
            ahora=ahora + timedelta(seconds=6),
        )

    otro_usuario = _crear_operador(db)
    otro_admin = otro_usuario.id
    otro_token = f"token-operador-limite-{uuid4().hex}"
    db.add(
        Sesion(
            usuario_id=otro_admin,
            token_hash=hash_token_sesion(otro_token),
            expira_en=ahora + timedelta(hours=1),
        )
    )
    db.commit()
    db.rollback()
    aperturas = []
    for _ in range(10):
        lease_id = admitir_conexion_sse(
            db,
            usuario_id=otro_admin,
            token_sesion=otro_token,
            ahora=ahora,
        )
        aperturas.append(lease_id)
        cerrar_conexion_sse(
            db,
            usuario_id=otro_admin,
            lease_id=lease_id,
            ahora=ahora,
        )
    with pytest.raises(LimiteConexionesSSEError):
        admitir_conexion_sse(
            db,
            usuario_id=otro_admin,
            token_sesion=otro_token,
            ahora=ahora + timedelta(seconds=1),
        )

    tercer_usuario = _crear_operador(db)
    tercero_admin = tercer_usuario.id
    tercer_token = f"token-operador-vigencia-{uuid4().hex}"
    db.add(
        Sesion(
            usuario_id=tercero_admin,
            token_hash=hash_token_sesion(tercer_token),
            expira_en=ahora + timedelta(hours=1),
        )
    )
    db.commit()
    db.rollback()
    lease_expirada = admitir_conexion_sse(
        db,
        usuario_id=tercero_admin,
        token_sesion=tercer_token,
        ahora=ahora,
    )
    resultado = consultar_lote_eventos_usuario(
        db,
        usuario_id=tercero_admin,
        rol_usuario="OPERADOR",
        token_sesion=tercer_token,
        lease_id=lease_expirada,
        cursor=0,
        revalidar_sesion=False,
        renovar_conexion=False,
        ahora=ahora + timedelta(seconds=46),
    )
    assert resultado.autorizado is False

    lease_renovable = admitir_conexion_sse(
        db,
        usuario_id=tercero_admin,
        token_sesion=tercer_token,
        ahora=ahora + timedelta(seconds=47),
    )
    resultado = consultar_lote_eventos_usuario(
        db,
        usuario_id=tercero_admin,
        rol_usuario="OPERADOR",
        token_sesion=tercer_token,
        lease_id=lease_renovable,
        cursor=0,
        revalidar_sesion=True,
        renovar_conexion=True,
        ahora=ahora + timedelta(seconds=62),
    )
    assert resultado.autorizado is True
    db.rollback()
    lease = db.get(ConexionSSEUsuario, lease_renovable)
    assert lease is not None
    assert lease.expira_en == ahora + timedelta(seconds=107)

    cerrar_conexion_sse(
        db,
        usuario_id=tercero_admin,
        lease_id=lease_renovable,
        ahora=ahora + timedelta(seconds=63),
    )
    admitir_conexion_sse(
        db,
        usuario_id=tercero_admin,
        token_sesion=tercer_token,
        ahora=ahora + timedelta(minutes=7),
    )
    db.rollback()
    assert (
        db.scalar(
            select(func.count())
            .select_from(ConexionSSEUsuario)
            .where(ConexionSSEUsuario.usuario_id == tercero_admin)
        )
        == 1
    )


@pytest.mark.parametrize("cambio", ["revocada", "expirada", "inactiva", "rol"])
def test_sesion_o_cuenta_invalida_cierra_la_conexion_en_la_revalidacion(
    db: Session,
    cambio: str,
) -> None:
    owner_id, token = _crear_owner(db)
    sesion = db.scalar(select(Sesion).where(Sesion.usuario_id == owner_id))
    assert sesion is not None
    ahora = datetime.now(UTC)
    owner = db.get(Usuario, owner_id)
    assert owner is not None
    lease_id = admitir_conexion_sse(
        db,
        usuario_id=owner_id,
        token_sesion=token,
        ahora=ahora,
    )
    if cambio == "revocada":
        sesion.revocado_en = ahora + timedelta(seconds=1)
    elif cambio == "expirada":
        sesion.expira_en = ahora + timedelta(seconds=1)
    elif cambio == "inactiva":
        owner.esta_activo = False
    else:
        owner.rol = RolUsuario.OPERADOR.value
    db.commit()
    db.rollback()

    resultado = consultar_lote_eventos_usuario(
        db,
        usuario_id=owner_id,
        rol_usuario="OWNER",
        token_sesion=token,
        lease_id=lease_id,
        cursor=0,
        revalidar_sesion=True,
        renovar_conexion=True,
        ahora=ahora + timedelta(seconds=15),
    )
    assert resultado.autorizado is False
    db.rollback()
    lease = db.get(ConexionSSEUsuario, lease_id)
    assert lease is not None
    assert lease.cerrada_en is not None


def test_admission_concurrente_respeta_el_limite_de_seis_streams(
    db: Session,
) -> None:
    owner_id, token = _crear_owner(db)
    ahora = datetime.now(UTC)
    for indice in range(5):
        admitir_conexion_sse(
            db,
            usuario_id=owner_id,
            token_sesion=token,
            ahora=ahora + timedelta(seconds=indice),
        )

    barrera = Barrier(3)
    resultados: list[str] = []
    errores: list[BaseException] = []
    motor = db.get_bind()
    assert isinstance(motor, Engine)

    def intentar_admision() -> None:
        try:
            with Session(
                bind=motor,
                autoflush=False,
                expire_on_commit=False,
            ) as otra_db:
                barrera.wait(timeout=10)
                try:
                    admitir_conexion_sse(
                        otra_db,
                        usuario_id=owner_id,
                        token_sesion=token,
                        ahora=ahora + timedelta(seconds=3),
                    )
                    resultados.append("aceptada")
                except LimiteConexionesSSEError:
                    resultados.append("limitada")
        except BaseException as error:
            errores.append(error)

    hilos = [Thread(target=intentar_admision, daemon=True) for _ in range(2)]
    for hilo in hilos:
        hilo.start()
    barrera.wait(timeout=10)
    for hilo in hilos:
        hilo.join(timeout=10)

    assert all(not hilo.is_alive() for hilo in hilos)
    assert not errores
    assert sorted(resultados) == ["aceptada", "limitada"]
    db.rollback()
    assert (
        db.scalar(
            select(func.count())
            .select_from(ConexionSSEUsuario)
            .where(
                ConexionSSEUsuario.usuario_id == owner_id,
                ConexionSSEUsuario.cerrada_en.is_(None),
                ConexionSSEUsuario.expira_en > ahora,
            )
        )
        == 6
    )


def test_mutaciones_visibles_emiten_y_reenvio_regeneracion_no(db: Session) -> None:
    owner_id, _token = _crear_owner(db)
    resultado = crear_operador(
        db,
        nombre="Grace",
        apellido_paterno="Hopper",
        apellido_materno="Murray",
        correo=_correo(),
        creado_por_usuario_id=owner_id,
        entregar_invitacion=lambda _usuario, _token: None,
        duracion_token_horas=24,
    )
    operador = resultado.usuario
    operador_id = operador.id

    ahora = datetime.now(UTC)
    assert _cantidad_eventos(db, operador_id) == 1
    reenviar_invitacion_operador(
        db,
        operador_id,
        cooldown_segundos=1,
        duracion_token_horas=24,
        entregar_invitacion=lambda _usuario, _token: None,
        ahora=ahora + timedelta(seconds=2),
    )
    assert _cantidad_eventos(db, operador_id) == 1

    activacion = db.scalar(
        select(ActivacionCuenta)
        .where(ActivacionCuenta.usuario_id == operador_id)
        .order_by(ActivacionCuenta.id.desc())
        .limit(1)
    )
    assert activacion is not None
    desafio = f"desafio-sintetico-{uuid4().hex}"
    activacion.desafio_hash = hash_token_activacion(desafio)
    activacion.desafio_expira_en = ahora + timedelta(hours=1)
    db.commit()
    db.rollback()

    completar_activacion_operador(
        db,
        token_desafio=desafio,
        nueva_contrasena="Contrasena sintetica segura 123",
        ahora=ahora + timedelta(seconds=3),
    )
    assert _cantidad_eventos(db, operador_id) == 2

    regenerar_contrasena_operador(
        db,
        operador_id,
        entregar_credencial=lambda _usuario, _contrasena: None,
    )
    assert _cantidad_eventos(db, operador_id) == 2

    desactivar_operador(db, operador_id)
    assert _cantidad_eventos(db, operador_id) == 3
    with pytest.raises(OperadorYaInactivoError):
        desactivar_operador(db, operador_id)
    assert _cantidad_eventos(db, operador_id) == 3

    reactivar_operador(db, operador_id)
    assert _cantidad_eventos(db, operador_id) == 4
    with pytest.raises(OperadorYaActivoError):
        reactivar_operador(db, operador_id)
    assert _cantidad_eventos(db, operador_id) == 4


def test_error_smtp_y_commit_fallido_no_dejan_eventos(db: Session) -> None:
    owner_id, _token = _crear_owner(db)
    correo_smtp = _correo()

    def fallar_invitacion(_usuario: Usuario, _token: str) -> None:
        raise ErrorEnvioCorreo

    with pytest.raises(ErrorEnvioCorreo):
        crear_operador(
            db,
            nombre="Grace",
            apellido_paterno="Hopper",
            apellido_materno="Murray",
            correo=correo_smtp,
            creado_por_usuario_id=owner_id,
            entregar_invitacion=fallar_invitacion,
            duracion_token_horas=24,
        )
    db.rollback()
    assert db.scalar(select(Usuario.id).where(Usuario.correo == correo_smtp)) is None
    db.rollback()
    assert db.scalar(select(func.count()).select_from(EventoTiempoReal)) == 0
    db.rollback()

    def fallar_commit(_sesion: Session) -> None:
        raise SQLAlchemyError("fallo controlado")

    event.listen(db, "before_commit", fallar_commit)
    try:
        with pytest.raises(SQLAlchemyError, match="fallo controlado"):
            crear_operador(
                db,
                nombre="Grace",
                apellido_paterno="Hopper",
                apellido_materno="Murray",
                correo=_correo(),
                creado_por_usuario_id=owner_id,
                entregar_invitacion=lambda _usuario, _token: None,
                duracion_token_horas=24,
            )
    finally:
        event.remove(db, "before_commit", fallar_commit)
        db.rollback()
    assert db.scalar(select(func.count()).select_from(EventoTiempoReal)) == 0
