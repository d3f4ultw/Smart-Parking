"""Contratos de cajones, autenticacion separada y cambios atomicos."""

from __future__ import annotations

import secrets
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app.api.dependencias as dependencias
import app.api.rutas.eventos as rutas_eventos
import main
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models import (
    Cajon,
    EstadoEfectivoCajon,
    EventoTiempoReal,
    RolUsuario,
    Sesion,
    Usuario,
)
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.cajones import obtener_estado_efectivo

NOMBRE_COOKIE_SESION = get_settings().session_cookie_name
HASH_SINTETICO = "hash-sintetico-cajones-test"


def _crear_settings(token: str | None) -> Settings:
    valores: dict[str, object] = {
        "database_host": "localhost",
        "database_port": 5432,
        "database_name": "smart_parking_test",
        "database_user": "smart_parking_test",
        "database_password": SecretStr("database-secret-test-only"),
        "activation_token_ttl_hours": 24,
        "activation_challenge_ttl_minutes": 15,
        "correo_transporte": "smtp",
        "smtp_host": "mailpit",
        "smtp_port": "1025",
        "smtp_from_email": "no-reply@example.test",
        "smtp_security": "none",
        "vision_bearer_token": SecretStr(token) if token is not None else None,
    }
    return Settings.model_validate(valores)


@pytest.fixture
def token_vision() -> str:
    """Token URL-safe efimero para probar la autorizacion de Vision."""

    return secrets.token_urlsafe(32)


@pytest.fixture
def client(
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
    token_vision: str,
) -> Generator[TestClient]:
    """Conecta la API y el poll SSE a la base temporal de la suite."""

    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    settings = _crear_settings(token_vision)

    def entregar_db() -> Generator[Session]:
        db = fabrica()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = entregar_db
    monkeypatch.setattr(dependencias, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(rutas_eventos, "SessionLocal", fabrica)
    try:
        with TestClient(main.app) as test_client:
            yield test_client
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        motor.dispose()


def _crear_personal(db: Session, rol: RolUsuario) -> tuple[int, str]:
    usuario = Usuario(
        nombre="Prueba",
        apellido_paterno="Cajones",
        apellido_materno="Sintetico",
        correo=f"cajones-{rol.value.lower()}-{uuid4().hex}@example.invalid",
        contrasena_hash=HASH_SINTETICO,
        rol=rol.value,
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(usuario)
    db.flush()
    token = secrets.token_urlsafe(32)
    db.add(
        Sesion(
            usuario_id=usuario.id,
            token_hash=hash_token_sesion(token),
            expira_en=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    usuario_id = usuario.id
    db.commit()
    db.rollback()
    return usuario_id, token


def _contar_eventos_cajon(db: Session, cajon_id: int = 1) -> int:
    db.rollback()
    cantidad = db.scalar(
        select(func.count())
        .select_from(EventoTiempoReal)
        .where(
            EventoTiempoReal.recurso_tipo == "cajon",
            EventoTiempoReal.recurso_id == cajon_id,
        )
    )
    db.rollback()
    return int(cantidad or 0)


def _autorizar_cookie(client: TestClient, token: str) -> None:
    client.cookies.set(NOMBRE_COOKIE_SESION, token)


def _quitar_cookie(client: TestClient) -> None:
    client.cookies.delete(NOMBRE_COOKIE_SESION)


def test_lista_admite_owner_y_operador_y_deniega_sin_sesion(
    client: TestClient,
    db: Session,
) -> None:
    _admin_id, token_admin = _crear_personal(db, RolUsuario.OWNER)
    _operador_id, token_operador = _crear_personal(db, RolUsuario.OPERADOR)

    anonima = client.get("/api/cajones")
    assert anonima.status_code == 401
    assert anonima.headers["cache-control"] == "no-store"

    respuestas = []
    for token in (token_admin, token_operador):
        _autorizar_cookie(client, token)
        respuestas.append(client.get("/api/cajones"))
        _quitar_cookie(client)

    for respuesta in respuestas:
        assert respuesta.status_code == 200
        assert respuesta.headers["cache-control"] == "no-store"
        cuerpo = respuesta.json()
        assert cuerpo["cursor_eventos"].isdigit()
        assert [cajon["numero"] for cajon in cuerpo["cajones"]] == [1]
        assert set(cuerpo["cajones"][0]) == {
            "id",
            "numero",
            "vision_zone_id",
            "activa",
            "estado_fisico",
            "estado_operativo",
            "motivo_operativo",
            "vision_desactualizada",
            "estado_fisico_actualizado_en",
            "estado_operativo_actualizado_en",
            "creado_en",
            "estado_efectivo",
        }
        assert cuerpo["vision"]["stale"] is True
        assert cuerpo["cajones"][0]["activa"] is True
        assert cuerpo["cajones"][0]["vision_desactualizada"] is True
        assert cuerpo["cajones"][0]["estado_fisico"] == "DESCONOCIDO"
        assert cuerpo["cajones"][0]["estado_operativo"] == "DISPONIBLE"
        assert cuerpo["cajones"][0]["estado_fisico_actualizado_en"] is None
        assert cuerpo["cajones"][0]["estado_efectivo"] == "DESCONOCIDO"


def test_mutacion_operativa_acepta_personal_y_respeta_no_op_y_cambio_de_motivo(
    client: TestClient,
    db: Session,
) -> None:
    _admin_id, token_admin = _crear_personal(db, RolUsuario.OWNER)
    _operador_id, token_operador = _crear_personal(db, RolUsuario.OPERADOR)

    _autorizar_cookie(client, token_admin)
    primera = client.patch(
        "/api/cajones/1/estado-operativo",
        json={"estado": "MANTENIMIENTO", "motivo": "  Revision anual  "},
    )
    assert primera.status_code == 200
    cuerpo_primero = primera.json()
    assert cuerpo_primero["cambio_aplicado"] is True
    assert cuerpo_primero["motivo_operativo"] == "Revision anual"
    assert cuerpo_primero["estado_fisico"] == "DESCONOCIDO"
    assert cuerpo_primero["estado_efectivo"] == "NO_DISPONIBLE"
    fecha_primera = cuerpo_primero["estado_operativo_actualizado_en"]
    assert _contar_eventos_cajon(db) == 1

    _quitar_cookie(client)
    _autorizar_cookie(client, token_operador)
    repetida = client.patch(
        "/api/cajones/1/estado-operativo",
        json={"estado": "MANTENIMIENTO", "motivo": "Revision anual"},
    )
    assert repetida.status_code == 200
    assert repetida.json()["cambio_aplicado"] is False
    assert repetida.json()["estado_operativo_actualizado_en"] == fecha_primera
    assert _contar_eventos_cajon(db) == 1

    cambio_motivo = client.patch(
        "/api/cajones/1/estado-operativo",
        json={"estado": "MANTENIMIENTO", "motivo": "Reparacion de sensor"},
    )
    assert cambio_motivo.status_code == 200
    assert cambio_motivo.json()["cambio_aplicado"] is True
    assert cambio_motivo.json()["estado_operativo"] == "MANTENIMIENTO"
    assert _contar_eventos_cajon(db) == 2
    _quitar_cookie(client)


def test_mutacion_operativa_acepta_mantenimiento_y_fuera_de_servicio_sin_motivo(
    client: TestClient,
    db: Session,
) -> None:
    _admin_id, token_admin = _crear_personal(db, RolUsuario.OWNER)
    _autorizar_cookie(client, token_admin)

    mantenimiento = client.patch(
        "/api/cajones/1/estado-operativo",
        json={"estado": "MANTENIMIENTO"},
    )
    assert mantenimiento.status_code == 200
    assert mantenimiento.json()["estado_operativo"] == "MANTENIMIENTO"
    assert mantenimiento.json()["motivo_operativo"] is None
    assert mantenimiento.json()["estado_efectivo"] == "NO_DISPONIBLE"
    assert mantenimiento.json()["cambio_aplicado"] is True

    mantenimiento_repetido = client.patch(
        "/api/cajones/1/estado-operativo",
        json={"estado": "MANTENIMIENTO", "motivo": "   "},
    )
    assert mantenimiento_repetido.status_code == 200
    assert mantenimiento_repetido.json()["motivo_operativo"] is None
    assert mantenimiento_repetido.json()["cambio_aplicado"] is False

    fuera_de_servicio = client.patch(
        "/api/cajones/1/estado-operativo",
        json={"estado": "FUERA_DE_SERVICIO", "motivo": ""},
    )
    assert fuera_de_servicio.status_code == 200
    assert fuera_de_servicio.json()["estado_operativo"] == "FUERA_DE_SERVICIO"
    assert fuera_de_servicio.json()["motivo_operativo"] is None
    assert fuera_de_servicio.json()["estado_efectivo"] == "NO_DISPONIBLE"
    assert fuera_de_servicio.json()["cambio_aplicado"] is True
    assert _contar_eventos_cajon(db) == 2
    _quitar_cookie(client)


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"estado": "MANTENIMIENTO", "motivo": "x" * 251},
        {"estado": "DISPONIBLE", "motivo": "No corresponde"},
        {"estado": "ESTACIONADO", "motivo": "Dato invalido"},
        {"estado": "MANTENIMIENTO", "motivo": "Valido", "extra": True},
    ],
)
def test_mutacion_operativa_rechaza_entradas_invalidas(
    client: TestClient,
    db: Session,
    cuerpo: dict[str, object],
) -> None:
    _admin_id, token_admin = _crear_personal(db, RolUsuario.OWNER)
    _autorizar_cookie(client, token_admin)
    respuesta = client.patch("/api/cajones/1/estado-operativo", json=cuerpo)
    assert respuesta.status_code == 422
    assert "x" * 251 not in respuesta.text
    assert _contar_eventos_cajon(db) == 0
    _quitar_cookie(client)


def test_mutacion_operativa_devuelve_404_y_solo_acepta_personal(
    client: TestClient,
    db: Session,
) -> None:
    _admin_id, token_admin = _crear_personal(db, RolUsuario.OWNER)
    respuesta_anonima = client.patch(
        "/api/cajones/1/estado-operativo",
        json={"estado": "DISPONIBLE"},
    )
    assert respuesta_anonima.status_code == 401

    ruta_heredada = client.put(
        "/api/cajones/1/estado-fisico",
        json={"ocupado": True},
    )
    assert ruta_heredada.status_code == 404

    _autorizar_cookie(client, token_admin)
    respuesta = client.patch(
        "/api/cajones/999/estado-operativo",
        json={"estado": "DISPONIBLE"},
    )
    assert respuesta.status_code == 404
    _quitar_cookie(client)


def test_estado_efectivo_cubre_precedencia_fisica_y_operativa() -> None:
    casos = [
        ("DESCONOCIDO", "DISPONIBLE", EstadoEfectivoCajon.DESCONOCIDO),
        ("LIBRE", "DISPONIBLE", EstadoEfectivoCajon.LIBRE),
        ("OCUPADO", "DISPONIBLE", EstadoEfectivoCajon.OCUPADO),
        ("LIBRE", "MANTENIMIENTO", EstadoEfectivoCajon.NO_DISPONIBLE),
        ("OCUPADO", "MANTENIMIENTO", EstadoEfectivoCajon.NO_DISPONIBLE),
        ("LIBRE", "FUERA_DE_SERVICIO", EstadoEfectivoCajon.NO_DISPONIBLE),
        ("OCUPADO", "FUERA_DE_SERVICIO", EstadoEfectivoCajon.NO_DISPONIBLE),
    ]
    for fisico, operativo, esperado in casos:
        cajon = Cajon(
            numero=1,
            estado_fisico=fisico,
            estado_operativo=operativo,
        )
        assert obtener_estado_efectivo(cajon) == esperado


def test_base_rechaza_numero_duplicado_no_positivo_y_estados_invalidos(
    db: Session,
) -> None:
    filas_invalidas = [
        Cajon(
            numero=1,
            vision_zone_id=uuid4(),
            poligono=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]],
        ),
        Cajon(
            numero=0,
            vision_zone_id=uuid4(),
            poligono=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]],
        ),
        Cajon(
            numero=9,
            vision_zone_id=uuid4(),
            poligono=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]],
            estado_fisico="EN_USO",
        ),
        Cajon(
            numero=9,
            vision_zone_id=uuid4(),
            poligono=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]],
            estado_operativo="PAUSADO",
        ),
    ]
    for fila in filas_invalidas:
        db.add(fila)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


@pytest.mark.parametrize("estado", ["MANTENIMIENTO", "FUERA_DE_SERVICIO"])
def test_base_permite_estado_no_disponible_sin_motivo(
    db: Session,
    estado: str,
) -> None:
    cajon = Cajon(
        numero=9,
        vision_zone_id=uuid4(),
        poligono=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]],
        estado_operativo=estado,
    )
    db.add(cajon)
    db.flush()

    assert cajon.motivo_operativo is None
    assert obtener_estado_efectivo(cajon) == EstadoEfectivoCajon.NO_DISPONIBLE
    db.rollback()
