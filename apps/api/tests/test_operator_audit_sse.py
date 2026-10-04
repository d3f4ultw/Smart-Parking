"""Pruebas focalizadas de auditoria y autorizacion del stream ADMIN."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.sse import ServerSentEvent
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.rutas import operadores as rutas_operadores
from app.core.config import Settings
from app.core.database import get_db
from app.models import (
    ConexionSSEAdmin,
    EstadoEventosOperadores,
    EventoOperador,
    RolUsuario,
    Sesion,
    Usuario,
)
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.eventos_operadores import (
    EventoSSE,
    ResultadoLoteEventosSSE,
    admitir_conexion_sse_admin,
)
from app.servicios.operadores import listar_operadores
from app.servicios.usuarios import crear_admin, crear_operador
from main import app

RUTA_OPERADORES = "/api/admin/operadores"
RUTA_EVENTOS = f"{RUTA_OPERADORES}/eventos"
NOMBRE_COOKIE = "smart_parking_session"
HASH_SINTETICO = "hash-sintetico-de-prueba"


def _correo() -> str:
    return f"audit-sse-{uuid4().hex}@example.com"


def _datos_sse(texto: str) -> object:
    linea_datos = next(
        linea.removeprefix("data: ")
        for linea in texto.splitlines()
        if linea.startswith("data: ")
    )
    return json.loads(linea_datos)


def _settings() -> Settings:
    return Settings(
        database_host="localhost",
        database_port=5432,
        database_name="unused",
        database_user="unused",
        database_password=SecretStr("synthetic-test-database-secret"),
        activation_token_ttl_hours=24,
        activation_challenge_ttl_minutes=15,
        smtp_from_email="no-reply@example.com",
    )


@pytest.fixture
def client(
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient]:
    """Usa la BD UUID de pruebas tambien para cada poll del SSE."""

    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)

    def entregar_db() -> Generator[Session]:
        db = fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = entregar_db
    monkeypatch.setattr(rutas_operadores, "SessionLocal", fabrica)
    try:
        with TestClient(app) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.pop(get_db, None)
        motor.dispose()


def _crear_admin(db: Session) -> tuple[int, str]:
    usuario = Usuario(
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=_correo(),
        contrasena_hash=HASH_SINTETICO,
        rol=RolUsuario.ADMIN.value,
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(usuario)
    db.flush()
    token = f"cookie-sintetica-{uuid4().hex}"
    db.add(
        Sesion(
            usuario_id=usuario.id,
            token_hash=hash_token_sesion(token),
            expira_en=datetime.now(UTC) + timedelta(minutes=30),
        )
    )
    usuario_id = usuario.id
    db.commit()
    db.rollback()
    return usuario_id, token


def _crear_sesion(db: Session, usuario: Usuario) -> str:
    token = f"cookie-sintetica-{uuid4().hex}"
    db.add(
        Sesion(
            usuario_id=usuario.id,
            token_hash=hash_token_sesion(token),
            expira_en=datetime.now(UTC) + timedelta(minutes=30),
        )
    )
    db.commit()
    db.rollback()
    return token


def _crear_operador(db: Session, admin_id: int, correo: str | None = None) -> Usuario:
    resultado = crear_operador(
        db,
        nombre="Grace",
        apellido_paterno="Hopper",
        apellido_materno="Murray",
        correo=correo or _correo(),
        creado_por_usuario_id=admin_id,
        entregar_invitacion=lambda _usuario, _token: None,
        duracion_token_horas=24,
    )
    db.rollback()
    return resultado.usuario


def _crear_operador_http(
    cliente: TestClient,
    token: str,
    correo: str,
    *,
    extra: dict[str, object] | None = None,
):
    datos: dict[str, object] = {
        "nombre": "Grace",
        "apellido_paterno": "Hopper",
        "apellido_materno": "Murray",
        "correo": correo,
    }
    if extra:
        datos.update(extra)
    cliente.cookies.set(NOMBRE_COOKIE, token)
    with (
        patch("app.api.rutas.operadores.get_settings", return_value=_settings()),
        patch("app.api.rutas.operadores.crear_transporte_correo") as crear_transporte,
    ):
        try:
            respuesta = cliente.post(RUTA_OPERADORES, json=datos)
        finally:
            cliente.cookies.delete(NOMBRE_COOKIE)
    return respuesta, crear_transporte


def test_creacion_http_guarda_el_admin_autenticado_y_evento_unico(
    db: Session,
    client: TestClient,
) -> None:
    admin_a_id, token_a = _crear_admin(db)
    admin_b_id, token_b = _crear_admin(db)
    correo_a = _correo()
    correo_b = _correo()

    respuesta_a, correo_a_mock = _crear_operador_http(client, token_a, correo_a)
    respuesta_b, correo_b_mock = _crear_operador_http(client, token_b, correo_b)

    assert respuesta_a.status_code == 201
    assert respuesta_b.status_code == 201
    correo_a_mock.return_value.enviar.assert_called_once()
    correo_b_mock.return_value.enviar.assert_called_once()

    db.rollback()
    operador_a = db.scalar(select(Usuario).where(Usuario.correo == correo_a))
    operador_b = db.scalar(select(Usuario).where(Usuario.correo == correo_b))
    assert operador_a is not None
    assert operador_b is not None
    assert operador_a.creado_por_usuario_id == admin_a_id
    assert operador_b.creado_por_usuario_id == admin_b_id
    assert operador_a.creado_en.tzinfo is not None
    assert operador_b.creado_en.tzinfo is not None

    from app.models import EventoOperador

    eventos = db.scalars(
        select(EventoOperador)
        .where(EventoOperador.operador_id.in_([operador_a.id, operador_b.id]))
        .order_by(EventoOperador.id)
    ).all()
    assert [evento.tipo for evento in eventos] == [
        "operador.creado",
        "operador.creado",
    ]


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("creado_por_usuario_id", 1),
        ("creado_en", "2020-01-01T00:00:00Z"),
    ],
)
def test_solicitud_no_puede_inyectar_campos_de_auditoria(
    db: Session,
    client: TestClient,
    campo: str,
    valor: object,
) -> None:
    _admin_id, token = _crear_admin(db)
    respuesta, correo_mock = _crear_operador_http(
        client,
        token,
        _correo(),
        extra={campo: valor},
    )

    assert respuesta.status_code == 422
    assert respuesta.json() == {"detail": "Solicitud invalida"}
    correo_mock.return_value.enviar.assert_not_called()


def test_creador_y_timestamp_se_exponen_en_lista_y_detalle_sin_secretos(
    db: Session,
    client: TestClient,
) -> None:
    admin_id, token = _crear_admin(db)
    operador = _crear_operador(db, admin_id)
    client.cookies.set(NOMBRE_COOKIE, token)
    with patch(
        "app.api.rutas.operadores.get_settings",
        return_value=_settings(),
    ):
        lista = client.get(RUTA_OPERADORES)
        detalle = client.get(f"{RUTA_OPERADORES}/{operador.id}")
    client.cookies.delete(NOMBRE_COOKIE)

    assert lista.status_code == 200
    assert detalle.status_code == 200
    assert lista.json()["cursor_eventos"].isdigit()
    registro_lista = next(
        fila for fila in lista.json()["operadores"] if fila["id"] == operador.id
    )
    registro_detalle = detalle.json()
    admin = db.get(Usuario, admin_id)
    assert admin is not None
    for registro in (registro_lista, registro_detalle):
        assert datetime.fromisoformat(registro["creado_en"]).utcoffset() is not None
        assert registro["creado_por"] == {
            "id": admin_id,
            "nombre": "Ada",
            "apellido_paterno": "Lovelace",
            "apellido_materno": "Byron",
            "correo": admin.correo,
        }
        assert set(registro["creado_por"]) == {
            "id",
            "nombre",
            "apellido_paterno",
            "apellido_materno",
            "correo",
        }
        for campo in (
            "contrasena_hash",
            "contrasena",
            "sesiones",
            "token",
            "token_hash",
            "activation_url",
            "challenge_hash",
            "smtp",
        ):
            assert campo not in registro


def test_listado_captura_cursor_antes_de_consultar_la_pagina(
    db: Session,
    client: TestClient,
) -> None:
    _admin_id, token = _crear_admin(db)
    llamadas: list[str] = []
    obtener_marca_original = rutas_operadores.obtener_marca_eventos
    listar_original = rutas_operadores.listar_operadores

    def registrar_marca(sesion: Session) -> tuple[int, int | None]:
        llamadas.append("cursor")
        return obtener_marca_original(sesion)

    def registrar_listado(sesion: Session, pagina: int):
        llamadas.append("pagina")
        return listar_original(sesion, pagina)

    client.cookies.set(NOMBRE_COOKIE, token)
    with (
        patch(
            "app.api.rutas.operadores.get_settings",
            return_value=_settings(),
        ),
        patch(
            "app.api.rutas.operadores.obtener_marca_eventos",
            side_effect=registrar_marca,
        ),
        patch(
            "app.api.rutas.operadores.listar_operadores",
            side_effect=registrar_listado,
        ),
    ):
        respuesta = client.get(RUTA_OPERADORES)
    client.cookies.delete(NOMBRE_COOKIE)

    assert respuesta.status_code == 200
    assert respuesta.json()["cursor_eventos"].isdigit()
    assert llamadas == ["cursor", "pagina"]


def test_listado_carga_creadores_en_lote_sin_n_mas_uno(db: Session) -> None:
    admin_id, _token = _crear_admin(db)
    for _ in range(10):
        db.add(
            Usuario(
                nombre="Operador",
                apellido_paterno="Prueba",
                apellido_materno="",
                correo=_correo(),
                rol=RolUsuario.OPERADOR.value,
                creado_por_usuario_id=admin_id,
            )
        )
    db.commit()
    db.rollback()

    motor = db.get_bind()
    consultas_usuarios: list[str] = []

    def capturar_consulta(
        _conexion: object,
        _cursor: object,
        sentencia: str,
        _parametros: object,
        _contexto: object,
        _muchos: bool,
    ) -> None:
        if sentencia.lstrip().lower().startswith("select") and "usuarios" in sentencia:
            consultas_usuarios.append(sentencia)

    event.listen(motor, "before_cursor_execute", capturar_consulta)
    try:
        resultado = listar_operadores(db, 1)
    finally:
        event.remove(motor, "before_cursor_execute", capturar_consulta)

    assert len(resultado.operadores) == 10
    assert len(consultas_usuarios) <= 3


def test_crear_admin_bootstrap_conserva_timestamp_db_y_creador_nulo(
    db: Session,
) -> None:
    resultado = crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=_correo(),
        contrasena="Contrasena sintetica 123",
        confirmacion_contrasena="Contrasena sintetica 123",
    )
    db.refresh(resultado.usuario)

    assert resultado.usuario.creado_en.tzinfo is not None
    assert resultado.usuario.creado_por_usuario_id is None


@pytest.mark.parametrize(
    "estado",
    ["sin_cookie", "operador", "expirada", "revocada", "inactiva"],
)
def test_sse_rechaza_sesiones_invalidas_y_cabeceras_falsas(
    db: Session,
    client: TestClient,
    estado: str,
) -> None:
    cookies: dict[str, str] | None = None
    if estado == "operador":
        operador = Usuario(
            nombre="Grace",
            apellido_paterno="Hopper",
            apellido_materno="Murray",
            correo=_correo(),
            contrasena_hash=HASH_SINTETICO,
            rol=RolUsuario.OPERADOR.value,
            correo_verificado=True,
            debe_cambiar_contrasena=False,
            esta_activo=True,
        )
        db.add(operador)
        db.flush()
        token = _crear_sesion(db, operador)
        cookies = {NOMBRE_COOKIE: token}
    elif estado != "sin_cookie":
        admin_id, token = _crear_admin(db)
        cookies = {NOMBRE_COOKIE: token}
        sesion = db.scalar(select(Sesion).where(Sesion.usuario_id == admin_id))
        usuario = db.get(Usuario, admin_id)
        assert sesion is not None
        assert usuario is not None
        if estado == "expirada":
            sesion.expira_en = datetime.now(UTC) - timedelta(seconds=1)
        elif estado == "revocada":
            sesion.revocado_en = datetime.now(UTC)
        elif estado == "inactiva":
            usuario.esta_activo = False
        db.commit()
        db.rollback()

    if cookies:
        client.cookies.set(NOMBRE_COOKIE, cookies[NOMBRE_COOKIE])
    try:
        respuesta = client.get(
            f"{RUTA_EVENTOS}?role=ADMIN&admin_id=1&token=forged",
            headers={"X-Role": "ADMIN", "X-User-Id": "1"},
        )
    finally:
        if cookies:
            client.cookies.delete(NOMBRE_COOKIE)

    assert respuesta.status_code == 401
    assert respuesta.headers.get("cache-control") == "no-store"


def test_sse_valido_devuelve_cabeceras_seguras_y_cierra_lease(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_id, token = _crear_admin(db)

    def consultar_lote(**argumentos: object) -> ResultadoLoteEventosSSE:
        if argumentos["cursor"] == 0:
            return ResultadoLoteEventosSSE(
                autorizado=True,
                marca=1,
                eventos=(
                    EventoSSE(
                        id=1,
                        tipo="operador.creado",
                        operador_id=44,
                        ocurrido_en="2026-10-04T12:00:00+00:00",
                    ),
                ),
            )
        return ResultadoLoteEventosSSE(autorizado=False, marca=1)

    monkeypatch.setattr(
        rutas_operadores,
        "_consultar_lote_en_sesion",
        consultar_lote,
    )

    client.cookies.set(NOMBRE_COOKIE, token)
    respuesta = client.get(RUTA_EVENTOS, headers={"Origin": "https://evil.example"})
    client.cookies.delete(NOMBRE_COOKIE)

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/event-stream")
    assert "no-store" in respuesta.headers["cache-control"]
    assert respuesta.headers["x-accel-buffering"] == "no"
    assert "id: 1" in respuesta.text
    assert "event: operador.creado" in respuesta.text
    assert _datos_sse(respuesta.text) == {
        "operador_id": 44,
        "ocurrido_en": "2026-10-04T12:00:00+00:00",
    }
    assert "set-cookie" not in respuesta.headers
    assert "authorization" not in respuesta.headers
    assert "cookie" not in respuesta.headers
    assert "access-control-allow-origin" not in respuesta.headers

    db.rollback()
    leases = db.scalars(
        select(ConexionSSEAdmin).where(
            ConexionSSEAdmin.admin_usuario_id == admin_id
        )
    ).all()
    assert len(leases) == 1
    assert leases[0].cerrada_en is not None


@pytest.mark.parametrize(
    "valor",
    ["", "x", "-1", "1", "1" + "0" * 19],
)
def test_last_event_id_invalido_se_rechaza_antes_de_abrir_lease(
    db: Session,
    client: TestClient,
    valor: str,
) -> None:
    admin_id, token = _crear_admin(db)
    client.cookies.set(NOMBRE_COOKIE, token)
    respuesta = client.get(RUTA_EVENTOS, headers={"Last-Event-ID": valor})
    client.cookies.delete(NOMBRE_COOKIE)

    assert respuesta.status_code == 400
    from app.models import ConexionSSEAdmin

    assert (
        db.scalar(
            select(func.count())
            .select_from(ConexionSSEAdmin)
            .where(ConexionSSEAdmin.admin_usuario_id == admin_id)
        )
        == 0
    )


def test_retention_gap_emite_resync_con_solo_metadata_segura(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_id, token = _crear_admin(db)
    operador = _crear_operador(db, admin_id)
    db.rollback()
    db.execute(delete(EventoOperador))
    estado = db.get(EstadoEventosOperadores, 1)
    assert estado is not None
    estado.ultimo_id = 4
    db.add(
        EventoOperador(
            id=4,
            operador_id=operador.id,
            tipo="operador.actualizado",
        )
    )
    db.commit()
    db.rollback()
    monkeypatch.setattr(
        rutas_operadores,
        "_consultar_lote_en_sesion",
        lambda **_kwargs: ResultadoLoteEventosSSE(autorizado=False, marca=4),
    )

    client.cookies.set(NOMBRE_COOKIE, token)
    respuesta = client.get(
        RUTA_EVENTOS,
        headers={"Last-Event-ID": "1"},
    )
    client.cookies.delete(NOMBRE_COOKIE)

    assert respuesta.status_code == 200
    assert "id: 4" in respuesta.text
    assert "event: resync" in respuesta.text
    assert _datos_sse(respuesta.text) == {
        "ultimo_id": 4,
        "motivo": "historial_expirado",
    }
    assert "cookie-sintetica" not in respuesta.text
    assert "hash-sintetico" not in respuesta.text


def test_sesion_y_transaccion_se_cierran_antes_de_yield_y_disconnect(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_id, token = _crear_admin(db)
    lease_id = admitir_conexion_sse_admin(
        db,
        admin_usuario_id=admin_id,
        token_sesion=token,
    )
    motor = db.get_bind()
    assert isinstance(motor, Engine)
    sesiones: list[SessionRastreada] = []
    limpiezas: list[UUID] = []

    class SessionRastreada(Session):
        cerrada_para_prueba = False

        def close(self) -> None:
            self.cerrada_para_prueba = True
            super().close()

    def crear_sesion_rastreada() -> SessionRastreada:
        sesion = SessionRastreada(bind=motor, autoflush=False, expire_on_commit=False)
        sesiones.append(sesion)
        return sesion

    evento = EventoSSE(
        id=1,
        tipo="operador.creado",
        operador_id=44,
        ocurrido_en="2026-10-04T12:00:00+00:00",
    )

    def consultar(_db: Session, **kwargs: object) -> ResultadoLoteEventosSSE:
        if kwargs["cursor"] == 0:
            return ResultadoLoteEventosSSE(
                autorizado=True,
                marca=1,
                eventos=(evento,),
            )
        return ResultadoLoteEventosSSE(autorizado=False, marca=1)

    monkeypatch.setattr(rutas_operadores, "SessionLocal", crear_sesion_rastreada)
    monkeypatch.setattr(rutas_operadores, "consultar_lote_eventos_sse", consultar)
    monkeypatch.setattr(
        rutas_operadores,
        "_cerrar_lease_en_sesion",
        lambda contexto: limpiezas.append(contexto.lease_id),
    )
    contexto = rutas_operadores.ContextoStreamOperadores(
        admin_usuario_id=admin_id,
        token_sesion=token,
        lease_id=lease_id,
        cursor=0,
        marca_inicial=0,
        requiere_resync=False,
    )

    async def recibir_y_cerrar() -> ServerSentEvent:
        generador = rutas_operadores._generar_eventos_operadores(contexto)
        recibido = await anext(generador)
        assert sesiones
        assert sesiones[0].cerrada_para_prueba is True
        assert not sesiones[0].in_transaction()
        await generador.aclose()
        return recibido

    recibido = asyncio.run(recibir_y_cerrar())

    assert recibido.event == "operador.creado"
    assert recibido.id == "1"
    assert recibido.data == {
        "operador_id": 44,
        "ocurrido_en": "2026-10-04T12:00:00+00:00",
    }
    assert limpiezas == [lease_id]
