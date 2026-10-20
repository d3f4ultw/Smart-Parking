from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

import app.api.dependencias_sesion_cliente as dependencias_sesion_cliente
import app.api.rutas.contrasena_clientes as rutas_contrasena_clientes
from app.core.database import get_db
from app.models import CuentaCliente, Sesion, SesionCliente, Usuario
from app.seguridad.contrasenas import crear_hash_contrasena, verificar_contrasena
from app.seguridad.sesiones import generar_token_sesion, hash_token_sesion

ORIGEN_WEB = "https://parking.example"
NOMBRE_COOKIE_CLIENTE = "smart_parking_customer_session"
NOMBRE_COOKIE_PERSONAL = "smart_parking_session"
CONTRASENA_ACTUAL = "Password1!"
CONTRASENA_NUEVA = "NuevaClave2!"


@pytest.fixture
def cliente_http(
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient]:
    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    aplicacion = FastAPI()
    aplicacion.include_router(rutas_contrasena_clientes.router)

    def entregar_db() -> Generator[Session]:
        sesion = fabrica()
        try:
            yield sesion
        finally:
            sesion.close()

    aplicacion.dependency_overrides[get_db] = entregar_db

    class SettingsPrueba:
        app_public_url = ORIGEN_WEB
        customer_session_cookie_name = NOMBRE_COOKIE_CLIENTE
        customer_session_cookie_secure = True

    settings = SettingsPrueba()
    monkeypatch.setattr(rutas_contrasena_clientes, "get_settings", lambda: settings)
    monkeypatch.setattr(
        dependencias_sesion_cliente,
        "get_settings",
        lambda: settings,
    )
    try:
        with TestClient(aplicacion, base_url=ORIGEN_WEB) as cliente:
            yield cliente
    finally:
        aplicacion.dependency_overrides.clear()
        motor.dispose()


def crear_cuenta(db: Session) -> CuentaCliente:
    cuenta = CuentaCliente(
        nombre="Ana",
        apellido_paterno="Pruebas",
        apellido_materno="Cliente",
        correo=f"cliente-{uuid4().hex}@example.com",
        contrasena_hash=crear_hash_contrasena(CONTRASENA_ACTUAL),
        correo_verificado=False,
        esta_activa=True,
    )
    db.add(cuenta)
    db.commit()
    db.refresh(cuenta)
    return cuenta


def agregar_sesion_cliente(
    db: Session,
    cuenta: CuentaCliente,
) -> str:
    token = generar_token_sesion()
    ahora = datetime.now(UTC)
    db.add(
        SesionCliente(
            cuenta_cliente_id=cuenta.id,
            token_hash=hash_token_sesion(token),
            creada_en=ahora,
            expira_en=ahora + timedelta(hours=8),
            revocada_en=None,
        )
    )
    db.commit()
    return token


def cabeceras_origen(origen: str | None = ORIGEN_WEB) -> dict[str, str]:
    return {} if origen is None else {"Origin": origen}


def solicitud_cambio(
    *,
    actual: str = CONTRASENA_ACTUAL,
    nueva: str = CONTRASENA_NUEVA,
    confirmacion: str = CONTRASENA_NUEVA,
) -> dict[str, str]:
    return {
        "contrasena_actual": actual,
        "contrasena_nueva": nueva,
        "confirmacion_contrasena_nueva": confirmacion,
    }


def obtener_sesion(db: Session, token: str) -> SesionCliente | None:
    return db.scalar(
        select(SesionCliente).where(
            SesionCliente.token_hash == hash_token_sesion(token)
        )
    )


def test_cambio_actualiza_hash_y_revoca_las_otras_sesiones(
    cliente_http: TestClient,
    db: Session,
) -> None:
    cuenta = crear_cuenta(db)
    token_actual = agregar_sesion_cliente(db, cuenta)
    token_otra_sesion = agregar_sesion_cliente(db, cuenta)
    otra_cuenta = crear_cuenta(db)
    token_otra_cuenta = agregar_sesion_cliente(db, otra_cuenta)
    usuario_personal = Usuario(
        nombre="Operador",
        apellido_paterno="Prueba",
        correo=f"operador-{uuid4().hex}@example.com",
        contrasena_hash="hash-no-autenticable-de-prueba",
        rol="OPERADOR",
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(usuario_personal)
    db.flush()
    token_personal = generar_token_sesion()
    sesion_personal = Sesion(
        usuario_id=usuario_personal.id,
        token_hash=hash_token_sesion(token_personal),
        expira_en=datetime.now(UTC) + timedelta(hours=8),
        revocado_en=None,
    )
    db.add(sesion_personal)
    db.commit()
    cliente_http.cookies.set(NOMBRE_COOKIE_CLIENTE, token_actual)
    cliente_http.cookies.set(NOMBRE_COOKIE_PERSONAL, token_personal)

    respuesta = cliente_http.post(
        "/api/clientes/contrasena",
        headers=cabeceras_origen(),
        json=solicitud_cambio(),
    )

    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "contrasena_actualizada"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert CONTRASENA_ACTUAL not in respuesta.text
    assert CONTRASENA_NUEVA not in respuesta.text
    assert cliente_http.cookies.get(NOMBRE_COOKIE_CLIENTE) == token_actual
    db.refresh(cuenta)
    assert verificar_contrasena(CONTRASENA_NUEVA, cuenta.contrasena_hash)
    assert not verificar_contrasena(CONTRASENA_ACTUAL, cuenta.contrasena_hash)

    db.expire_all()
    sesion_actual = obtener_sesion(db, token_actual)
    sesion_otra = obtener_sesion(db, token_otra_sesion)
    sesion_otra_cuenta = obtener_sesion(db, token_otra_cuenta)
    sesion_personal_persistida = db.scalar(
        select(Sesion).where(Sesion.token_hash == hash_token_sesion(token_personal))
    )
    assert sesion_actual is not None and sesion_actual.revocada_en is None
    assert sesion_otra is not None and sesion_otra.revocada_en is not None
    assert sesion_otra_cuenta is not None and sesion_otra_cuenta.revocada_en is None
    assert (
        sesion_personal_persistida is not None
        and sesion_personal_persistida.revocado_en is None
    )


def test_contrasena_actual_incorrecta_no_cambia_hash_ni_sesiones(
    cliente_http: TestClient,
    db: Session,
) -> None:
    cuenta = crear_cuenta(db)
    token_actual = agregar_sesion_cliente(db, cuenta)
    token_otra_sesion = agregar_sesion_cliente(db, cuenta)
    hash_anterior = cuenta.contrasena_hash
    cliente_http.cookies.set(NOMBRE_COOKIE_CLIENTE, token_actual)

    respuesta = cliente_http.post(
        "/api/clientes/contrasena",
        headers=cabeceras_origen(),
        json=solicitud_cambio(actual="NoEsLaActual1!"),
    )

    assert respuesta.status_code == 400
    assert respuesta.headers["cache-control"] == "no-store"
    assert "NoEsLaActual1!" not in respuesta.text
    assert CONTRASENA_NUEVA not in respuesta.text
    db.refresh(cuenta)
    assert cuenta.contrasena_hash == hash_anterior
    sesion_actual = obtener_sesion(db, token_actual)
    sesion_otra = obtener_sesion(db, token_otra_sesion)
    assert sesion_actual is not None and sesion_actual.revocada_en is None
    assert sesion_otra is not None and sesion_otra.revocada_en is None


@pytest.mark.parametrize(
    ("nueva", "confirmacion"),
    [
        ("minusculas2!", "minusculas2!"),
        ("Corta1!", "Corta1!"),
        (CONTRASENA_NUEVA, "OtraClave3!"),
    ],
)
def test_rechaza_contrasena_nueva_fuera_de_politica_sin_reflejar_secretos(
    cliente_http: TestClient,
    db: Session,
    nueva: str,
    confirmacion: str,
) -> None:
    cuenta = crear_cuenta(db)
    token = agregar_sesion_cliente(db, cuenta)
    hash_anterior = cuenta.contrasena_hash
    cliente_http.cookies.set(NOMBRE_COOKIE_CLIENTE, token)

    respuesta = cliente_http.post(
        "/api/clientes/contrasena",
        headers=cabeceras_origen(),
        json=solicitud_cambio(nueva=nueva, confirmacion=confirmacion),
    )

    assert respuesta.status_code == 422
    assert respuesta.json() == {"detail": "La solicitud no es válida"}
    assert respuesta.headers["cache-control"] == "no-store"
    for secreto in (CONTRASENA_ACTUAL, nueva, confirmacion):
        assert secreto not in respuesta.text
    db.refresh(cuenta)
    assert cuenta.contrasena_hash == hash_anterior
    sesion = obtener_sesion(db, token)
    assert sesion is not None and sesion.revocada_en is None


@pytest.mark.parametrize("origen", [None, "https://attacker.example"])
def test_origin_ausente_o_ajeno_rechaza_cambio_sin_mutar_cuenta(
    cliente_http: TestClient,
    db: Session,
    origen: str | None,
) -> None:
    cuenta = crear_cuenta(db)
    token = agregar_sesion_cliente(db, cuenta)
    hash_anterior = cuenta.contrasena_hash
    cliente_http.cookies.set(NOMBRE_COOKIE_CLIENTE, token)

    respuesta = cliente_http.post(
        "/api/clientes/contrasena",
        headers=cabeceras_origen(origen),
        json=solicitud_cambio(),
    )

    assert respuesta.status_code == 403
    assert respuesta.headers["cache-control"] == "no-store"
    assert CONTRASENA_ACTUAL not in respuesta.text
    assert CONTRASENA_NUEVA not in respuesta.text
    db.refresh(cuenta)
    assert cuenta.contrasena_hash == hash_anterior
    sesion = obtener_sesion(db, token)
    assert sesion is not None and sesion.revocada_en is None


def test_requiere_sesion_cliente_y_no_refleja_json_malformado(
    cliente_http: TestClient,
    db: Session,
) -> None:
    sin_sesion = cliente_http.post(
        "/api/clientes/contrasena",
        headers=cabeceras_origen(),
        json=solicitud_cambio(),
    )
    assert sin_sesion.status_code == 401
    assert sin_sesion.headers["cache-control"] == "no-store"

    cuenta = crear_cuenta(db)
    token = agregar_sesion_cliente(db, cuenta)
    cliente_http.cookies.set(NOMBRE_COOKIE_CLIENTE, token)
    secreto = "ClavePrivadaEnJSON!"
    malformado = cliente_http.post(
        "/api/clientes/contrasena",
        headers=cabeceras_origen(),
        content=f'{{"contrasena_actual":"{secreto}"'.encode(),
    )

    assert malformado.status_code == 422
    assert malformado.json() == {"detail": "La solicitud no es válida"}
    assert malformado.headers["cache-control"] == "no-store"
    assert secreto not in malformado.text
