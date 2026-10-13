from __future__ import annotations

import secrets
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

import app.api.dependencias as dependencias
import app.api.rutas.eventos as rutas_eventos
import main
from app.core.config import Settings
from app.core.database import get_db
from app.models import (
    ConfiguracionEstacionamiento,
    HistorialModalidadEstacionamiento,
    RolUsuario,
    Sesion,
    Usuario,
)
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.configuracion_estacionamiento import (
    listar_historial_modalidad,
    obtener_configuracion_estacionamiento,
)

NOMBRE_COOKIE_SESION = "smart_parking_session"


def _crear_settings() -> Settings:
    return Settings.model_validate(
        {
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
        }
    )


@pytest.fixture
def client(
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient]:
    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    settings = _crear_settings()

    def entregar_db() -> Generator[Session]:
        sesion = fabrica()
        try:
            yield sesion
        finally:
            sesion.close()

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


def _crear_usuario(
    db: Session,
    rol: str | None,
    *,
    activo: bool = True,
    correo: str | None = None,
) -> int:
    usuario = Usuario(
        nombre="Prueba",
        apellido_paterno="Fase seis",
        apellido_materno="Sintetico",
        correo=correo or f"phase6-{uuid4().hex}@example.invalid",
        contrasena_hash="hash-sintetico-phase6",
        rol=rol,
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=activo,
    )
    db.add(usuario)
    db.flush()
    usuario_id = usuario.id
    db.commit()
    db.rollback()
    return usuario_id


def _crear_sesion(
    db: Session,
    usuario_id: int,
    *,
    expira_en: datetime | None = None,
    revocada: bool = False,
) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        Sesion(
            usuario_id=usuario_id,
            token_hash=hash_token_sesion(token),
            expira_en=expira_en or datetime.now(UTC) + timedelta(hours=1),
            revocado_en=datetime.now(UTC) if revocada else None,
        )
    )
    db.commit()
    db.rollback()
    return token


def _usar_sesion(client: TestClient, token: str | None) -> None:
    if token is None:
        client.cookies.delete(NOMBRE_COOKIE_SESION)
    else:
        client.cookies.set(NOMBRE_COOKIE_SESION, token)


def test_owner_consulta_y_cambia_las_tres_modalidades_sin_writes_repetidos(
    client: TestClient,
    db: Session,
) -> None:
    usuario_id = _crear_usuario(db, RolUsuario.OWNER.value)
    _usar_sesion(client, _crear_sesion(db, usuario_id))

    inicial = client.get("/api/admin/configuracion/modalidad")
    assert inicial.status_code == 200
    assert inicial.headers["cache-control"] == "no-store"
    assert inicial.json() == {
        "modalidad": None,
        "revision": 0,
        "acceso_suspendido": False,
    }

    revision = 0
    for modalidad in ("PRIVADO", "PUBLICO", "MIXTO"):
        respuesta = client.put(
            "/api/admin/configuracion/modalidad",
            json={"modalidad": modalidad, "revision_esperada": revision},
        )
        assert respuesta.status_code == 200
        assert respuesta.headers["cache-control"] == "no-store"
        revision += 1
        assert respuesta.json() == {
            "modalidad": modalidad,
            "revision": revision,
            "acceso_suspendido": False,
        }

    repetida = client.put(
        "/api/admin/configuracion/modalidad",
        json={"modalidad": "MIXTO", "revision_esperada": revision},
    )
    assert repetida.status_code == 200
    assert repetida.json() == {
        "modalidad": "MIXTO",
        "revision": revision,
        "acceso_suspendido": False,
    }
    assert len(listar_historial_modalidad(db)) == 3

    obsoleta = client.put(
        "/api/admin/configuracion/modalidad",
        json={"modalidad": "PRIVADO", "revision_esperada": 0},
    )
    assert obsoleta.status_code == 409
    assert obsoleta.headers["cache-control"] == "no-store"
    assert client.get("/api/admin/configuracion/modalidad").json() == {
        "modalidad": "MIXTO",
        "revision": 3,
        "acceso_suspendido": False,
    }

    for cuerpo in (
        {"modalidad": "privado", "revision_esperada": 3},
        {"modalidad": "MIXTO", "revision_esperada": True},
        {
            "modalidad": "MIXTO",
            "revision_esperada": 3,
            "configuracion_extra": "no permitida",
        },
    ):
        respuesta = client.put("/api/admin/configuracion/modalidad", json=cuerpo)
        assert respuesta.status_code == 422
        assert respuesta.json() == {"detail": "Solicitud invalida"}

    estado = obtener_configuracion_estacionamiento(db)
    assert estado is not None
    assert estado.modalidad == "MIXTO"
    assert estado.revision == 3


def test_owner_suspende_reanuda_y_preserva_modalidad_y_revision(
    client: TestClient,
    db: Session,
) -> None:
    usuario_id = _crear_usuario(db, RolUsuario.OWNER.value)
    _usar_sesion(client, _crear_sesion(db, usuario_id))

    sin_configurar = client.put(
        "/api/admin/configuracion/acceso",
        json={"acceso_suspendido": True, "revision_esperada": 0},
    )
    assert sin_configurar.status_code == 409
    assert sin_configurar.headers["cache-control"] == "no-store"
    assert db.get(ConfiguracionEstacionamiento, 1) is None

    inicial = client.put(
        "/api/admin/configuracion/modalidad",
        json={"modalidad": "MIXTO", "revision_esperada": 0},
    )
    assert inicial.status_code == 200
    assert inicial.json() == {
        "modalidad": "MIXTO",
        "revision": 1,
        "acceso_suspendido": False,
    }

    suspendida = client.put(
        "/api/admin/configuracion/acceso",
        json={"acceso_suspendido": True, "revision_esperada": 1},
    )
    assert suspendida.status_code == 200
    assert suspendida.headers["cache-control"] == "no-store"
    assert suspendida.json() == {
        "modalidad": "MIXTO",
        "revision": 2,
        "acceso_suspendido": True,
    }

    modalidad_bloqueada = client.put(
        "/api/admin/configuracion/modalidad",
        json={"modalidad": "PUBLICO", "revision_esperada": 2},
    )
    assert modalidad_bloqueada.status_code == 409
    assert modalidad_bloqueada.headers["cache-control"] == "no-store"
    assert "suspendido" in modalidad_bloqueada.json()["detail"]

    repetida = client.put(
        "/api/admin/configuracion/acceso",
        json={"acceso_suspendido": True, "revision_esperada": 2},
    )
    assert repetida.status_code == 200
    assert repetida.json()["revision"] == 2
    assert len(listar_historial_modalidad(db)) == 1

    obsoleta = client.put(
        "/api/admin/configuracion/acceso",
        json={"acceso_suspendido": False, "revision_esperada": 1},
    )
    assert obsoleta.status_code == 409
    assert obsoleta.headers["cache-control"] == "no-store"

    reanudada = client.put(
        "/api/admin/configuracion/acceso",
        json={"acceso_suspendido": False, "revision_esperada": 2},
    )
    assert reanudada.status_code == 200
    assert reanudada.json() == {
        "modalidad": "MIXTO",
        "revision": 3,
        "acceso_suspendido": False,
    }
    assert len(listar_historial_modalidad(db)) == 1

    for cuerpo in (
        {"acceso_suspendido": "true", "revision_esperada": 3},
        {"acceso_suspendido": 1, "revision_esperada": 3},
        {"acceso_suspendido": False, "revision_esperada": True},
        {
            "acceso_suspendido": False,
            "revision_esperada": 3,
            "configuracion_extra": "no permitida",
        },
    ):
        respuesta = client.put("/api/admin/configuracion/acceso", json=cuerpo)
        assert respuesta.status_code == 422
        assert respuesta.headers["cache-control"] == "no-store"
        assert respuesta.json() == {"detail": "Solicitud invalida"}


def test_api_rechaza_roles_y_sesiones_que_no_sean_owner_vigente(
    client: TestClient,
    db: Session,
) -> None:
    admin_id = _crear_usuario(db, RolUsuario.ADMIN.value)
    operador_id = _crear_usuario(db, RolUsuario.OPERADOR.value)
    sin_rol_id = _crear_usuario(db, None)
    owner_inactivo_id = _crear_usuario(db, RolUsuario.OWNER.value, activo=False)
    owner_id = _crear_usuario(db, RolUsuario.OWNER.value)

    casos = (
        (None, 401),
        (_crear_sesion(db, admin_id), 403),
        (_crear_sesion(db, operador_id), 403),
        (_crear_sesion(db, sin_rol_id), 401),
        (_crear_sesion(db, owner_inactivo_id), 401),
        (
            _crear_sesion(
                db,
                owner_id,
                expira_en=datetime.now(UTC) - timedelta(seconds=1),
            ),
            401,
        ),
        (_crear_sesion(db, owner_id, revocada=True), 401),
    )

    for token, codigo in casos:
        _usar_sesion(client, token)
        lectura = client.get("/api/admin/configuracion/modalidad")
        escritura = client.put(
            "/api/admin/configuracion/modalidad",
            json={"modalidad": "PRIVADO", "revision_esperada": 0},
        )
        acceso = client.put(
            "/api/admin/configuracion/acceso",
            json={"acceso_suspendido": True, "revision_esperada": 0},
        )
        assert lectura.status_code == codigo
        assert escritura.status_code == codigo
        assert acceso.status_code == codigo
        assert lectura.headers["cache-control"] == "no-store"
        assert escritura.headers["cache-control"] == "no-store"
        assert acceso.headers["cache-control"] == "no-store"

    assert db.query(HistorialModalidadEstacionamiento).count() == 0


def test_autorizacion_sigue_el_rol_persistido_y_no_la_identidad_del_owner(
    client: TestClient,
    db: Session,
) -> None:
    owner_id = _crear_usuario(db, RolUsuario.OWNER.value)
    token_anterior = _crear_sesion(db, owner_id)
    owner = db.get(Usuario, owner_id)
    assert owner is not None
    owner.correo = "cambio-correo-owner@example.invalid"
    db.commit()
    db.rollback()

    _usar_sesion(client, token_anterior)
    cambio = client.put(
        "/api/admin/configuracion/modalidad",
        json={"modalidad": "PRIVADO", "revision_esperada": 0},
    )
    assert cambio.status_code == 200

    owner = db.get(Usuario, owner_id)
    assert owner is not None
    owner.rol = RolUsuario.ADMIN.value
    db.commit()
    db.rollback()

    _usar_sesion(client, token_anterior)
    assert client.get("/api/admin/configuracion/modalidad").status_code == 403
    assert client.put(
        "/api/admin/configuracion/modalidad",
        json={"modalidad": "PUBLICO", "revision_esperada": 1},
    ).status_code == 403
    assert client.put(
        "/api/admin/configuracion/acceso",
        json={"acceso_suspendido": True, "revision_esperada": 1},
    ).status_code == 403

    owner_nuevo_id = _crear_usuario(
        db,
        RolUsuario.OWNER.value,
        correo="owner-reemplazo@example.invalid",
    )
    token_nuevo = _crear_sesion(db, owner_nuevo_id)
    _usar_sesion(client, token_nuevo)
    lectura = client.get("/api/admin/configuracion/modalidad")
    assert lectura.status_code == 200
    assert lectura.json() == {
        "modalidad": "PRIVADO",
        "revision": 1,
        "acceso_suspendido": False,
    }

    reemplazo = client.put(
        "/api/admin/configuracion/modalidad",
        json={"modalidad": "PUBLICO", "revision_esperada": 1},
    )
    assert reemplazo.status_code == 200
    assert reemplazo.json() == {
        "modalidad": "PUBLICO",
        "revision": 2,
        "acceso_suspendido": False,
    }

    _usar_sesion(client, token_anterior)
    assert client.put(
        "/api/admin/configuracion/modalidad",
        json={"modalidad": "MIXTO", "revision_esperada": 2},
    ).status_code == 403
