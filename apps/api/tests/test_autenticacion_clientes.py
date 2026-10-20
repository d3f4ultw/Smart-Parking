from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

import app.api.dependencias_sesion_cliente as dependencias_cliente
import app.api.rutas.autenticacion_clientes as rutas_autenticacion_cliente
from app.core.database import get_db
from app.models import CuentaCliente, Sesion, SesionCliente, Usuario
from app.seguridad.contrasenas import crear_hash_contrasena
from app.seguridad.correos import huella_correo
from app.seguridad.limitador import limitador_autenticacion
from app.seguridad.limitador_clientes import limitador_autenticacion_clientes
from app.seguridad.sesiones import generar_token_sesion, hash_token_sesion

ORIGEN_WEB = "https://parking.example"
NOMBRE_COOKIE_CLIENTE = "smart_parking_customer_session"
NOMBRE_COOKIE_PERSONAL = "smart_parking_session"
CONTRASENA = "Password1!"


@dataclass(frozen=True)
class SettingsClientePrueba:
    app_public_url: str = ORIGEN_WEB
    customer_session_cookie_name: str = NOMBRE_COOKIE_CLIENTE
    customer_session_duration_minutes: int = 480
    customer_session_cookie_secure: bool = True


@pytest.fixture(autouse=True)
def limpiar_estado_autenticacion() -> Generator[None]:
    limitador_autenticacion_clientes.reiniciar()
    limitador_autenticacion.reiniciar()
    yield
    limitador_autenticacion_clientes.reiniciar()
    limitador_autenticacion.reiniciar()


@pytest.fixture(autouse=True)
def limpiar_sesiones_clientes(db: Session) -> Generator[None]:
    """Limpia primero la tabla nueva antes del teardown general de cuentas."""

    yield
    db.execute(delete(SesionCliente))
    db.commit()


@pytest.fixture
def cliente_http(
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient]:
    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    settings = SettingsClientePrueba()
    aplicacion = FastAPI()
    aplicacion.include_router(rutas_autenticacion_cliente.router)

    def entregar_db() -> Generator[Session]:
        sesion = fabrica()
        try:
            yield sesion
        finally:
            sesion.close()

    aplicacion.dependency_overrides[get_db] = entregar_db
    monkeypatch.setattr(rutas_autenticacion_cliente, "get_settings", lambda: settings)
    monkeypatch.setattr(dependencias_cliente, "get_settings", lambda: settings)
    try:
        with TestClient(aplicacion, base_url=ORIGEN_WEB) as cliente:
            yield cliente
    finally:
        aplicacion.dependency_overrides.clear()
        motor.dispose()


def crear_cuenta(
    db: Session,
    *,
    correo: str | None = None,
    activa: bool = True,
    verificada: bool = False,
) -> CuentaCliente:
    cuenta = CuentaCliente(
        nombre="Ana",
        apellido_paterno="Pruebas",
        apellido_materno="Cliente",
        correo=correo or f"cliente-{uuid4().hex}@example.com",
        contrasena_hash=crear_hash_contrasena(CONTRASENA),
        correo_verificado=verificada,
        esta_activa=activa,
    )
    db.add(cuenta)
    db.commit()
    db.refresh(cuenta)
    return cuenta


def cabeceras_origen() -> dict[str, str]:
    return {"Origin": ORIGEN_WEB}


def test_login_crea_sesion_hash_cookie_segura_y_acepta_correo_no_verificado(
    cliente_http: TestClient,
    db: Session,
) -> None:
    correo = f"Cliente-{uuid4().hex}@Example.com"
    cuenta = crear_cuenta(db, correo=correo.casefold())

    respuesta = cliente_http.post(
        "/api/clientes/autenticacion/login",
        headers=cabeceras_origen(),
        json={"correo": correo, "contrasena": CONTRASENA},
    )

    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "credenciales_validas"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert CONTRASENA not in respuesta.text
    token = cliente_http.cookies.get(NOMBRE_COOKIE_CLIENTE)
    assert token is not None
    assert token not in respuesta.text
    cookie = respuesta.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Domain=" not in cookie

    sesion = db.scalar(
        select(SesionCliente).where(
            SesionCliente.token_hash == hash_token_sesion(token)
        )
    )
    assert sesion is not None
    assert sesion.cuenta_cliente_id == cuenta.id
    assert sesion.token_hash != token
    assert sesion.revocada_en is None
    assert sesion.expira_en > datetime.now(UTC)


def test_me_devuelve_solo_datos_del_cliente_autenticado(
    cliente_http: TestClient,
    db: Session,
) -> None:
    cuenta = crear_cuenta(db, verificada=False)
    login = cliente_http.post(
        "/api/clientes/autenticacion/login",
        headers=cabeceras_origen(),
        json={"correo": cuenta.correo, "contrasena": CONTRASENA},
    )
    assert login.status_code == 200

    respuesta = cliente_http.get("/api/clientes/autenticacion/me")

    assert respuesta.status_code == 200
    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.json() == {
        "autenticado": True,
        "cliente": {
            "nombre": "Ana",
            "apellido_paterno": "Pruebas",
            "apellido_materno": "Cliente",
            "correo": cuenta.correo,
            "correo_verificado": False,
        },
    }
    assert "id" not in respuesta.json()["cliente"]
    assert "contrasena_hash" not in respuesta.text


def test_credenciales_inexistentes_incorrectas_e_inactivas_son_indistinguibles(
    cliente_http: TestClient,
    db: Session,
) -> None:
    activa = crear_cuenta(db)
    inactiva = crear_cuenta(db, activa=False)
    solicitudes = (
        {"correo": f"ausente-{uuid4().hex}@example.com", "contrasena": CONTRASENA},
        {"correo": activa.correo, "contrasena": "Incorrecta1!"},
        {"correo": inactiva.correo, "contrasena": CONTRASENA},
    )

    respuestas = [
        cliente_http.post(
            "/api/clientes/autenticacion/login",
            headers=cabeceras_origen(),
            json=solicitud,
        )
        for solicitud in solicitudes
    ]

    assert [respuesta.status_code for respuesta in respuestas] == [401, 401, 401]
    assert respuestas[0].content == respuestas[1].content == respuestas[2].content
    assert all(
        respuesta.headers["cache-control"] == "no-store"
        for respuesta in respuestas
    )
    assert all("set-cookie" not in respuesta.headers for respuesta in respuestas)


def test_sesion_personal_no_autentica_en_me_de_cliente(
    cliente_http: TestClient,
) -> None:
    cliente_http.cookies.set(NOMBRE_COOKIE_PERSONAL, generar_token_sesion())

    respuesta = cliente_http.get("/api/clientes/autenticacion/me")

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "No autenticado"}
    assert respuesta.headers["cache-control"] == "no-store"


def test_sesion_vencida_o_cuenta_deshabilitada_no_autentican(
    cliente_http: TestClient,
    db: Session,
) -> None:
    cuenta_vencida = crear_cuenta(db)
    token_vencido = generar_token_sesion()
    db.add(
        SesionCliente(
            cuenta_cliente_id=cuenta_vencida.id,
            token_hash=hash_token_sesion(token_vencido),
            creada_en=datetime.now(UTC) - timedelta(hours=9),
            expira_en=datetime.now(UTC) - timedelta(seconds=1),
            revocada_en=None,
        )
    )
    cuenta_deshabilitada = crear_cuenta(db)
    token_deshabilitado = generar_token_sesion()
    db.add(
        SesionCliente(
            cuenta_cliente_id=cuenta_deshabilitada.id,
            token_hash=hash_token_sesion(token_deshabilitado),
            creada_en=datetime.now(UTC),
            expira_en=datetime.now(UTC) + timedelta(hours=1),
            revocada_en=None,
        )
    )
    db.commit()

    cliente_http.cookies.set(NOMBRE_COOKIE_CLIENTE, token_vencido)
    vencida = cliente_http.get("/api/clientes/autenticacion/me")
    assert vencida.status_code == 401

    cuenta_deshabilitada.esta_activa = False
    db.commit()
    cliente_http.cookies.set(NOMBRE_COOKIE_CLIENTE, token_deshabilitado)
    deshabilitada = cliente_http.get("/api/clientes/autenticacion/me")

    assert deshabilitada.status_code == 401
    assert vencida.content == deshabilitada.content


def test_logout_revoca_solo_sesion_cliente_y_limpia_su_cookie(
    cliente_http: TestClient,
    db: Session,
) -> None:
    cuenta = crear_cuenta(db)
    token_cliente = generar_token_sesion()
    db.add(
        SesionCliente(
            cuenta_cliente_id=cuenta.id,
            token_hash=hash_token_sesion(token_cliente),
            creada_en=datetime.now(UTC),
            expira_en=datetime.now(UTC) + timedelta(hours=1),
            revocada_en=None,
        )
    )
    usuario = Usuario(
        nombre="Operador",
        apellido_paterno="Prueba",
        correo=f"personal-{uuid4().hex}@example.com",
        contrasena_hash="hash-no-autenticable-de-prueba",
        rol="OPERADOR",
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(usuario)
    db.flush()
    token_personal = generar_token_sesion()
    sesion_personal = Sesion(
        usuario_id=usuario.id,
        token_hash=hash_token_sesion(token_personal),
        expira_en=datetime.now(UTC) + timedelta(hours=1),
        revocado_en=None,
    )
    db.add(sesion_personal)
    db.commit()

    cliente_http.cookies.set(NOMBRE_COOKIE_CLIENTE, token_cliente)
    cliente_http.cookies.set(NOMBRE_COOKIE_PERSONAL, token_personal)
    respuesta = cliente_http.post(
        "/api/clientes/autenticacion/logout",
        headers=cabeceras_origen(),
    )

    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "sesion_cerrada"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert "smart_parking_customer_session=" in respuesta.headers["set-cookie"]
    assert "Path=/" in respuesta.headers["set-cookie"]
    assert NOMBRE_COOKIE_PERSONAL in cliente_http.cookies
    db.expire_all()
    sesion_cliente = db.scalar(
        select(SesionCliente).where(
            SesionCliente.token_hash == hash_token_sesion(token_cliente)
        )
    )
    personal_persistida = db.scalar(
        select(Sesion).where(Sesion.token_hash == hash_token_sesion(token_personal))
    )
    assert sesion_cliente is not None and sesion_cliente.revocada_en is not None
    assert personal_persistida is not None and personal_persistida.revocado_en is None
    cliente_http.cookies.set(NOMBRE_COOKIE_CLIENTE, token_cliente)
    assert cliente_http.get("/api/clientes/autenticacion/me").status_code == 401


@pytest.mark.parametrize("origin", [None, "https://attacker.example"])
def test_login_y_logout_rechazan_origin_que_no_coincide(
    cliente_http: TestClient,
    origin: str | None,
) -> None:
    headers = {} if origin is None else {"Origin": origin}

    login = cliente_http.post(
        "/api/clientes/autenticacion/login",
        headers=headers,
        json={"correo": "alguien@example.com", "contrasena": CONTRASENA},
    )
    logout = cliente_http.post("/api/clientes/autenticacion/logout", headers=headers)

    assert login.status_code == logout.status_code == 403
    assert (
        login.headers["cache-control"]
        == logout.headers["cache-control"]
        == "no-store"
    )
    assert "set-cookie" not in login.headers


def test_limitador_de_cliente_no_consumo_el_cupo_de_personal(
    cliente_http: TestClient,
) -> None:
    correo = f"no-existe-{uuid4().hex}@example.com"

    for _ in range(5):
        respuesta = cliente_http.post(
            "/api/clientes/autenticacion/login",
            headers=cabeceras_origen(),
            json={"correo": correo, "contrasena": CONTRASENA},
        )
        assert respuesta.status_code == 401

    bloqueada = cliente_http.post(
        "/api/clientes/autenticacion/login",
        headers=cabeceras_origen(),
        json={"correo": correo, "contrasena": CONTRASENA},
    )

    assert bloqueada.status_code == 429
    assert limitador_autenticacion.permitir(
        "testclient",
        huella_correo(correo),
    )
