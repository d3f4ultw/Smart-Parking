"""Regresiones SP-027: login y sesión compartidos entre roles."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from solicitud_cliente import solicitar_con_cookies
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import get_db
from app.models import RolUsuario, Sesion, Usuario
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.usuarios import crear_admin
from main import app

RUTA_LOGIN = "/api/autenticacion/login"
RUTA_ME = "/api/autenticacion/me"
RUTA_LOGOUT = "/api/autenticacion/logout"
NOMBRE_COOKIE = "smart_parking_session"
CONTRASENA_PRUEBA = "Contrasena segura SP027 123"


def correo_de_prueba() -> str:
    return f"sp027-test-{uuid4().hex}@example.com"


def crear_usuario_activado(db: Session, rol: RolUsuario) -> Usuario:
    resultado = crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo_de_prueba(),
        contrasena=CONTRASENA_PRUEBA,
        confirmacion_contrasena=CONTRASENA_PRUEBA,
    )
    usuario = resultado.usuario
    usuario.rol = rol.value
    usuario.correo_verificado = True
    usuario.esta_activo = True
    usuario.debe_cambiar_contrasena = False
    db.commit()
    db.rollback()
    return usuario


def extraer_cookie(respuesta) -> str:
    cookies = SimpleCookie()
    cookies.load(respuesta.headers["set-cookie"])
    return cookies[NOMBRE_COOKIE].value


def crear_sesion(
    db: Session,
    usuario: Usuario,
    *,
    expirada: bool = False,
    revocada: bool = False,
) -> str:
    ahora = datetime.now(UTC)
    token = f"token-sp027-{uuid4().hex}"
    db.add(
        Sesion(
            usuario_id=usuario.id,
            token_hash=hash_token_sesion(token),
            expira_en=(
                ahora - timedelta(seconds=1)
                if expirada
                else ahora + timedelta(minutes=30)
            ),
            revocado_en=ahora if revocada else None,
            creado_en=ahora,
        )
    )
    db.commit()
    db.rollback()
    return token


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


@pytest.mark.parametrize("rol", list(RolUsuario))
def test_login_y_me_devuelven_el_rol_persistido(
    db: Session,
    client: TestClient,
    rol: RolUsuario,
) -> None:
    usuario = crear_usuario_activado(db, rol)

    respuesta_login = client.post(
        RUTA_LOGIN,
        json={"correo": usuario.correo, "contrasena": CONTRASENA_PRUEBA},
    )

    assert respuesta_login.status_code == 200
    assert respuesta_login.json() == {
        "estado": "credenciales_validas",
        "rol": rol.value,
    }
    assert respuesta_login.headers["cache-control"] == "no-store"
    cookie = SimpleCookie()
    cookie.load(respuesta_login.headers["set-cookie"])
    assert cookie[NOMBRE_COOKIE].value
    assert cookie[NOMBRE_COOKIE]["httponly"] is True
    assert cookie[NOMBRE_COOKIE]["samesite"].lower() == "lax"

    respuesta_me = client.get(RUTA_ME)

    assert respuesta_me.status_code == 200
    assert respuesta_me.headers["cache-control"] == "no-store"
    assert respuesta_me.json() == {
        "autenticado": True,
        "usuario": {
            "nombre": "Ada",
            "apellido_paterno": "Lovelace",
            "apellido_materno": "Byron",
            "correo": usuario.correo,
            "rol": rol.value,
        },
    }
    assert "contrasena_hash" not in respuesta_me.text
    assert "token_hash" not in respuesta_me.text


def test_login_no_acepta_que_el_cliente_asigne_el_rol(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_activado(db, RolUsuario.OPERADOR)

    respuesta = client.post(
        RUTA_LOGIN,
        json={
            "correo": usuario.correo,
            "contrasena": CONTRASENA_PRUEBA,
            "rol": RolUsuario.ADMIN.value,
        },
    )

    assert respuesta.status_code == 422
    assert respuesta.json() == {"detail": "Solicitud invalida"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert "set-cookie" not in respuesta.headers
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0


@pytest.mark.parametrize("rol", list(RolUsuario))
def test_logout_revoca_la_sesion_de_cualquier_rol(
    db: Session,
    client: TestClient,
    rol: RolUsuario,
) -> None:
    usuario = crear_usuario_activado(db, rol)
    respuesta_login = client.post(
        RUTA_LOGIN,
        json={"correo": usuario.correo, "contrasena": CONTRASENA_PRUEBA},
    )
    token = extraer_cookie(respuesta_login)

    respuesta_logout = solicitar_con_cookies(
        client,
        "POST",
        RUTA_LOGOUT,
        cookies={NOMBRE_COOKIE: token},
    )
    respuesta_me = solicitar_con_cookies(
        client, "GET", RUTA_ME, cookies={NOMBRE_COOKIE: token}
    )

    assert respuesta_logout.status_code == 200
    assert respuesta_logout.json() == {"estado": "sesion_cerrada"}
    assert respuesta_logout.headers["cache-control"] == "no-store"
    cookie_expirada = SimpleCookie()
    cookie_expirada.load(respuesta_logout.headers["set-cookie"])
    assert cookie_expirada[NOMBRE_COOKIE].value == ""
    assert cookie_expirada[NOMBRE_COOKIE]["max-age"] == "0"
    assert respuesta_me.status_code == 401
    assert respuesta_me.json() == {"detail": "No autenticado"}
    db.rollback()
    sesion = db.scalar(
        select(Sesion).where(Sesion.token_hash == hash_token_sesion(token))
    )
    assert sesion is not None
    assert sesion.revocado_en is not None
    assert sesion.revocado_en.tzinfo is not None


def test_usuario_inactivo_no_recibe_rol_ni_cookie(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_activado(db, RolUsuario.OPERADOR)
    usuario.esta_activo = False
    db.commit()

    respuesta = client.post(
        RUTA_LOGIN,
        json={"correo": usuario.correo, "contrasena": CONTRASENA_PRUEBA},
    )

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "Credenciales invalidas"}
    assert "set-cookie" not in respuesta.headers
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0


@pytest.mark.parametrize("estado", ["expirada", "revocada"])
def test_me_rechaza_sesion_operador_expirada_o_revocada(
    db: Session,
    client: TestClient,
    estado: str,
) -> None:
    usuario = crear_usuario_activado(db, RolUsuario.OPERADOR)
    token = crear_sesion(
        db,
        usuario,
        expirada=estado == "expirada",
        revocada=estado == "revocada",
    )

    respuesta = solicitar_con_cookies(
        client, "GET", RUTA_ME, cookies={NOMBRE_COOKIE: token}
    )

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "No autenticado"}
    assert respuesta.headers["cache-control"] == "no-store"
