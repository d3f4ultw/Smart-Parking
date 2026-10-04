"""Regresiones de SP-010: sesión ADMIN y cookie HttpOnly."""

from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.database import get_db
from app.models import Sesion, Usuario
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.autenticacion import crear_sesion_admin
from app.servicios.usuarios import crear_admin
from main import app

RUTA_LOGIN = "/api/autenticacion/login"
CONTRASENA_PRUEBA = "Contrasena segura SP010 123"
NOMBRE_COOKIE = "smart_parking_session"


def crear_usuario_activado(db: Session) -> Usuario:
    """Crea el único estado de ADMIN apto para iniciar sesión."""

    contrasena = CONTRASENA_PRUEBA
    resultado = crear_admin(
        db,
        nombre="Grace",
        apellido_paterno="Hopper",
        apellido_materno="Murray",
        correo=f"sp010-{uuid4().hex}@example.com",
        contrasena=contrasena,
        confirmacion_contrasena=contrasena,
    )
    usuario = resultado.usuario
    usuario.correo_verificado = True
    usuario.esta_activo = True
    usuario.debe_cambiar_contrasena = False
    db.commit()
    db.rollback()
    return usuario


@pytest.fixture
def client(database_url: URL) -> Generator[TestClient]:
    """Expone la API con conexiones independientes a la base temporal."""

    test_engine = create_engine(database_url, pool_pre_ping=True)
    fabrica_sesiones = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[Session]:
        db = fabrica_sesiones()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        test_engine.dispose()


def _token_cookie(respuesta) -> str:
    cookies = SimpleCookie()
    cookies.load(respuesta.headers["set-cookie"])
    return cookies[NOMBRE_COOKIE].value


def test_login_crea_sesion_persistida_y_cookie_segura_en_desarrollo(
    db: Session,
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    usuario = crear_usuario_activado(db)
    caplog.set_level("INFO")

    respuesta = client.post(
        RUTA_LOGIN,
        json={"correo": usuario.correo, "contrasena": CONTRASENA_PRUEBA},
    )

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "estado": "credenciales_validas",
        "rol": "ADMIN",
    }
    assert respuesta.headers["cache-control"] == "no-store"
    assert "token" not in respuesta.json()
    token = _token_cookie(respuesta)
    cabecera_cookie = respuesta.headers["set-cookie"].lower()
    assert "httponly" in cabecera_cookie
    assert "samesite=lax" in cabecera_cookie
    assert "path=/" in cabecera_cookie
    assert "secure" not in cabecera_cookie

    db.rollback()
    sesiones = db.scalars(select(Sesion).where(Sesion.usuario_id == usuario.id)).all()
    assert len(sesiones) == 1
    sesion = sesiones[0]
    assert sesion.token_hash == hash_token_sesion(token)
    assert token not in sesion.token_hash
    assert sesion.expira_en is not None
    assert sesion.revocado_en is None
    assert token not in respuesta.text
    assert token not in caplog.text


def test_produccion_marca_cookie_como_secure(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_activado(db)
    settings = Settings.model_validate(
        {
            "DATABASE_HOST": "localhost",
            "DATABASE_PORT": 5432,
            "DATABASE_NAME": "base",
            "DATABASE_USER": "usuario",
            "DATABASE_PASSWORD": "secreto",
            "ACTIVATION_TOKEN_TTL_HOURS": "24",
            "ACTIVATION_CHALLENGE_TTL_MINUTES": "15",
            "APP_ENVIRONMENT": "production",
            "CORREO_TRANSPORTE": "smtp",
        }
    )

    with patch("app.api.rutas.autenticacion.get_settings", return_value=settings):
        respuesta = client.post(
            RUTA_LOGIN,
            json={"correo": usuario.correo, "contrasena": CONTRASENA_PRUEBA},
        )

    assert respuesta.status_code == 200
    assert "secure" in respuesta.headers["set-cookie"].lower()


@pytest.mark.parametrize(
    "estado",
    ["contrasena_incorrecta", "desconocido", "inactivo", "no_verificado", "temporal"],
)
def test_login_no_crea_sesion_para_credenciales_o_estados_no_validos(
    db: Session,
    client: TestClient,
    estado: str,
) -> None:
    usuario = crear_usuario_activado(db)
    correo = usuario.correo
    contrasena = CONTRASENA_PRUEBA
    if estado == "contrasena_incorrecta":
        contrasena = "Contrasena incorrecta SP010"
    elif estado == "desconocido":
        correo = f"desconocido-{uuid4().hex}@example.com"
    elif estado == "inactivo":
        usuario.esta_activo = False
        db.commit()
    elif estado == "no_verificado":
        usuario.correo_verificado = False
        db.commit()
    elif estado == "temporal":
        usuario.debe_cambiar_contrasena = True
        db.commit()
    db.rollback()

    respuesta = client.post(
        RUTA_LOGIN,
        json={"correo": correo, "contrasena": contrasena},
    )

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "Credenciales invalidas"}
    assert "set-cookie" not in respuesta.headers
    assert respuesta.headers["cache-control"] == "no-store"
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0


def test_fallo_al_persistir_sesion_devuelve_500_sin_cookie_ni_sesion(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_activado(db)

    with patch(
        "app.api.rutas.autenticacion.crear_sesion_usuario",
        side_effect=SQLAlchemyError("fallo deliberado de persistencia"),
    ):
        respuesta = client.post(
            RUTA_LOGIN,
            json={"correo": usuario.correo, "contrasena": CONTRASENA_PRUEBA},
        )

    assert respuesta.status_code == 500
    assert respuesta.json() == {"detail": "Error interno"}
    assert "set-cookie" not in respuesta.headers
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0


def test_dos_logins_validos_crean_tokens_y_sesiones_distintos(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_activado(db)

    respuestas = [
        client.post(
            RUTA_LOGIN,
            json={"correo": usuario.correo, "contrasena": CONTRASENA_PRUEBA},
        )
        for _ in range(2)
    ]

    assert [respuesta.status_code for respuesta in respuestas] == [200, 200]
    tokens = {_token_cookie(respuesta) for respuesta in respuestas}
    assert len(tokens) == 2
    db.rollback()
    sesiones = db.scalars(select(Sesion).where(Sesion.usuario_id == usuario.id)).all()
    assert len(sesiones) == 2
    assert {sesion.token_hash for sesion in sesiones} == {
        hash_token_sesion(token) for token in tokens
    }


def test_logins_concurrentes_crean_sesiones_independientes(
    db: Session,
    database_url: URL,
) -> None:
    """Comprueba que dos logins simultáneos no reutilizan su token ni sesión."""

    usuario = crear_usuario_activado(db)
    fabrica_sesiones = sessionmaker(
        bind=create_engine(database_url, pool_pre_ping=True),
        autoflush=False,
        expire_on_commit=False,
    )

    def iniciar_sesion() -> str:
        sesion_db = fabrica_sesiones()
        try:
            resultado = crear_sesion_admin(
                sesion_db,
                correo=usuario.correo,
                contrasena=CONTRASENA_PRUEBA,
                correo_normalizado=usuario.correo,
                duracion_minutos=480,
            )
            assert resultado is not None
            return resultado.token
        finally:
            sesion_db.close()

    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        tokens = set(ejecutor.map(lambda _: iniciar_sesion(), range(2)))

    assert len(tokens) == 2
    db.rollback()
    sesiones = db.scalars(select(Sesion).where(Sesion.usuario_id == usuario.id)).all()
    assert len(sesiones) == 2
