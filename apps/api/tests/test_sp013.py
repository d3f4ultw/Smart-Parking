"""Regresiones de SP-013: sesión actual y acceso ADMIN."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from solicitud_cliente import solicitar_con_cookies
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import get_db
from app.models import Sesion, Usuario
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.usuarios import crear_admin
from main import app

RUTA_LOGIN = "/api/autenticacion/login"
RUTA_ME = "/api/autenticacion/me"
NOMBRE_COOKIE = "smart_parking_session"
CONTRASENA_PRUEBA = "Contrasena segura SP013 123"


def correo_de_prueba() -> str:
    return f"sp013-test-{uuid4().hex}@example.com"


def crear_usuario_activado(db: Session) -> Usuario:
    resultado = crear_admin(
        db,
        nombre="Katherine",
        apellido_paterno="Johnson",
        apellido_materno="Coleman",
        correo=correo_de_prueba(),
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
    token = f"token-sp013-{uuid4().hex}"
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


def test_me_devuelve_solo_la_identidad_minima_del_admin(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_activado(db)
    token, hash_token = crear_sesion(db, usuario)

    respuesta = solicitar_con_cookies(
        client, "GET", RUTA_ME, cookies={NOMBRE_COOKIE: token}
    )

    assert respuesta.status_code == 200
    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.json() == {
        "autenticado": True,
        "usuario": {
            "nombre": "Katherine",
            "apellido_paterno": "Johnson",
            "apellido_materno": "Coleman",
            "correo": usuario.correo,
            "rol": "ADMIN",
        },
    }
    assert token not in respuesta.text
    assert hash_token not in respuesta.text
    assert "contrasena_hash" not in respuesta.text
    assert "expira_en" not in respuesta.text
    assert "revocado_en" not in respuesta.text


@pytest.mark.parametrize(
    "cookies",
    [None, {NOMBRE_COOKIE: "token-aleatorio-sp013"}],
    ids=["sin_cookie", "cookie_aleatoria"],
)
def test_me_rechaza_sesiones_ausentes_o_desconocidas(
    client: TestClient,
    cookies: dict[str, str] | None,
) -> None:
    respuesta = solicitar_con_cookies(client, "GET", RUTA_ME, cookies=cookies)

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "No autenticado"}
    assert respuesta.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "estado",
    [
        "expirada",
        "revocada",
        "inactiva",
        "no_verificada",
        "debe_cambiar_contrasena",
    ],
)
def test_me_rechaza_cualquier_estado_no_utilizable(
    db: Session,
    client: TestClient,
    estado: str,
) -> None:
    usuario = crear_usuario_activado(db)
    ahora = datetime.now(UTC)
    token, _ = crear_sesion(
        db,
        usuario,
        expira_en=(ahora - timedelta(seconds=1) if estado == "expirada" else None),
        revocado_en=(ahora if estado == "revocada" else None),
    )

    if estado == "inactiva":
        usuario.esta_activo = False
    elif estado == "no_verificada":
        usuario.correo_verificado = False
    elif estado == "debe_cambiar_contrasena":
        usuario.debe_cambiar_contrasena = True
    db.commit()
    db.rollback()

    respuesta = solicitar_con_cookies(
        client, "GET", RUTA_ME, cookies={NOMBRE_COOKIE: token}
    )

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "No autenticado"}
    assert respuesta.headers["cache-control"] == "no-store"


def test_login_existente_y_me_comparten_la_cookie_de_sesion(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_activado(db)

    respuesta_login = client.post(
        RUTA_LOGIN,
        json={"correo": usuario.correo, "contrasena": CONTRASENA_PRUEBA},
    )
    assert respuesta_login.status_code == 200

    cookies = SimpleCookie()
    cookies.load(respuesta_login.headers["set-cookie"])
    assert NOMBRE_COOKIE in cookies

    respuesta_me = client.get(RUTA_ME)

    assert respuesta_me.status_code == 200
    assert respuesta_me.json()["usuario"]["correo"] == usuario.correo


def test_error_de_persistencia_se_trata_como_sesion_no_autenticada(
    client: TestClient,
) -> None:
    with patch(
        "app.api.rutas.autenticacion.obtener_usuario_por_token",
        side_effect=SQLAlchemyError("fallo deliberado de lectura"),
    ):
        respuesta = solicitar_con_cookies(
            client,
            "GET",
            RUTA_ME,
            cookies={NOMBRE_COOKIE: "token-de-prueba-sp013"},
        )

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "No autenticado"}
    assert respuesta.headers["cache-control"] == "no-store"
