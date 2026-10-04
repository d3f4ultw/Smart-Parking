"""Regresiones de SP-014: logout y revocación de la sesión actual."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from solicitud_cliente import solicitar_con_cookies
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import get_db
from app.models import Sesion, Usuario
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.usuarios import crear_admin
from main import app

RUTA_LOGOUT = "/api/autenticacion/logout"
RUTA_ME = "/api/autenticacion/me"
NOMBRE_COOKIE = "smart_parking_session"
CONTRASENA_PRUEBA = "Contrasena segura SP014 123"


def crear_usuario_activado(db: Session) -> Usuario:
    resultado = crear_admin(
        db,
        nombre="Margaret",
        apellido_paterno="Hamilton",
        apellido_materno="Heafield",
        correo=f"sp014-{uuid4().hex}@example.com",
        contrasena=CONTRASENA_PRUEBA,
        confirmacion_contrasena=CONTRASENA_PRUEBA,
    )
    usuario = resultado.usuario
    usuario.correo_verificado = True
    usuario.esta_activo = True
    usuario.debe_cambiar_contrasena = False
    db.commit()
    db.rollback()
    return usuario


def crear_sesion(
    db: Session,
    usuario: Usuario,
    *,
    expira_en: datetime | None = None,
    revocado_en: datetime | None = None,
) -> tuple[str, str]:
    ahora = datetime.now(UTC)
    token = f"token-sp014-{uuid4().hex}"
    hash_token = hash_token_sesion(token)
    sesion = Sesion(
        usuario_id=usuario.id,
        token_hash=hash_token,
        expira_en=expira_en or ahora + timedelta(minutes=30),
        revocado_en=revocado_en,
        creado_en=ahora,
    )
    db.add(sesion)
    db.commit()
    db.rollback()
    return token, hash_token


@pytest.fixture
def client(database_url: URL) -> Generator[TestClient]:
    test_engine = create_engine(database_url, pool_pre_ping=True)
    test_session_factory = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[Session]:
        session = test_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        test_engine.dispose()


def assert_cookie_eliminada(respuesta) -> None:
    assert "set-cookie" in respuesta.headers
    cookies = SimpleCookie()
    cookies.load(respuesta.headers["set-cookie"])
    cookie = cookies[NOMBRE_COOKIE]
    assert cookie.value == ""
    assert cookie["max-age"] == "0"
    assert cookie["path"] == "/"
    assert cookie["httponly"] is True
    assert cookie["samesite"].lower() == "lax"
    assert "secure" not in respuesta.headers["set-cookie"].lower()


def assert_logout_exitoso(respuesta) -> None:
    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "sesion_cerrada"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert_cookie_eliminada(respuesta)


def test_logout_revoca_sesion_actual_y_expira_cookie(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_activado(db)
    token, hash_token = crear_sesion(db, usuario)

    respuesta = solicitar_con_cookies(
        client, "POST", RUTA_LOGOUT, cookies={NOMBRE_COOKIE: token}
    )

    assert_logout_exitoso(respuesta)
    db.rollback()
    sesion = db.scalar(select(Sesion).where(Sesion.token_hash == hash_token))
    assert sesion is not None
    assert sesion.revocado_en is not None
    assert sesion.revocado_en.tzinfo is not None


def test_token_previamente_cerrado_no_puede_usar_me(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_activado(db)
    token, _ = crear_sesion(db, usuario)

    respuesta_logout = solicitar_con_cookies(
        client, "POST", RUTA_LOGOUT, cookies={NOMBRE_COOKIE: token}
    )
    respuesta_me = solicitar_con_cookies(
        client, "GET", RUTA_ME, cookies={NOMBRE_COOKIE: token}
    )

    assert_logout_exitoso(respuesta_logout)
    assert respuesta_me.status_code == 401
    assert respuesta_me.json() == {"detail": "No autenticado"}
    assert respuesta_me.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "cookies",
    [None, {NOMBRE_COOKIE: "cookie-aleatoria-sp014"}],
    ids=["sin_cookie", "cookie_aleatoria"],
)
def test_logout_idempotente_para_cookie_ausente_o_desconocida(
    client: TestClient,
    cookies: dict[str, str] | None,
) -> None:
    respuesta = solicitar_con_cookies(client, "POST", RUTA_LOGOUT, cookies=cookies)

    assert_logout_exitoso(respuesta)


@pytest.mark.parametrize("estado", ["revocada", "expirada"])
def test_logout_idempotente_para_sesion_ya_no_valida(
    db: Session,
    client: TestClient,
    estado: str,
) -> None:
    usuario = crear_usuario_activado(db)
    ahora = datetime.now(UTC)
    token, hash_token = crear_sesion(
        db,
        usuario,
        expira_en=(ahora - timedelta(seconds=1) if estado == "expirada" else None),
        revocado_en=(ahora if estado == "revocada" else None),
    )

    respuesta = solicitar_con_cookies(
        client, "POST", RUTA_LOGOUT, cookies={NOMBRE_COOKIE: token}
    )

    assert_logout_exitoso(respuesta)
    db.rollback()
    sesion = db.scalar(select(Sesion).where(Sesion.token_hash == hash_token))
    assert sesion is not None
    if estado == "revocada":
        assert sesion.revocado_en is not None
    else:
        assert sesion.revocado_en is None


def test_logout_solo_revoca_la_sesion_representada_por_su_cookie(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_activado(db)
    token_a, hash_token_a = crear_sesion(db, usuario)
    token_b, hash_token_b = crear_sesion(db, usuario)

    respuesta = solicitar_con_cookies(
        client, "POST", RUTA_LOGOUT, cookies={NOMBRE_COOKIE: token_a}
    )

    assert_logout_exitoso(respuesta)
    db.rollback()
    sesion_a = db.scalar(select(Sesion).where(Sesion.token_hash == hash_token_a))
    sesion_b = db.scalar(select(Sesion).where(Sesion.token_hash == hash_token_b))
    assert sesion_a is not None
    assert sesion_a.revocado_en is not None
    assert sesion_b is not None
    assert sesion_b.revocado_en is None
    assert (
        solicitar_con_cookies(
            client, "GET", RUTA_ME, cookies={NOMBRE_COOKIE: token_b}
        ).status_code
        == 200
    )


def test_fallo_de_persistencia_no_finge_logout_ni_expira_cookie(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_activado(db)
    token, hash_token = crear_sesion(db, usuario)

    with patch(
        "app.api.rutas.autenticacion.revocar_sesion_actual",
        side_effect=SQLAlchemyError("fallo deliberado de persistencia"),
    ):
        respuesta = solicitar_con_cookies(
            client, "POST", RUTA_LOGOUT, cookies={NOMBRE_COOKIE: token}
        )

    assert respuesta.status_code == 500
    assert respuesta.json() == {"detail": "Error interno"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert "set-cookie" not in respuesta.headers
    assert "fallo deliberado" not in respuesta.text
    db.rollback()
    sesion = db.scalar(select(Sesion).where(Sesion.token_hash == hash_token))
    assert sesion is not None
    assert sesion.revocado_en is None


def test_logout_no_expone_token_hash_ni_id_de_sesion(
    db: Session,
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    usuario = crear_usuario_activado(db)
    token, hash_token = crear_sesion(db, usuario)
    db.rollback()
    sesion = db.scalar(select(Sesion).where(Sesion.token_hash == hash_token))
    assert sesion is not None
    identificador_sesion = str(sesion.id)
    caplog.set_level("INFO")

    respuesta = solicitar_con_cookies(
        client, "POST", RUTA_LOGOUT, cookies={NOMBRE_COOKIE: token}
    )

    assert_logout_exitoso(respuesta)
    for valor_sensible in (token, hash_token, identificador_sesion):
        assert valor_sensible not in respuesta.text
        assert valor_sensible not in caplog.text
