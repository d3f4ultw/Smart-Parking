"""Pruebas del enlace de primera activacion OPERADOR."""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from http.cookies import SimpleCookie
from threading import Barrier
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from solicitud_cliente import solicitar_con_cookies
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.api.rutas.activaciones_operador import NOMBRE_COOKIE_DESAFIO
from app.core.config import Settings
from app.core.database import get_db
from app.correo.errores import ErrorCorreo, ErrorEnvioCorreo
from app.models import ActivacionCuenta, RolUsuario, Sesion, Usuario
from app.seguridad.activaciones import hash_token_activacion
from app.seguridad.contrasenas import verificar_contrasena
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.activaciones_operador import (
    ActivacionOperadorNoDisponible,
    canjear_enlace_operador,
    completar_activacion_operador,
)
from app.servicios.operadores import (
    desactivar_operador as desactivar_operador_servicio,
)
from app.servicios.operadores import (
    reenviar_invitacion_operador as reenviar_invitacion_operador_servicio,
)
from app.servicios.usuarios import (
    crear_admin,
    crear_admin_pendiente,
)
from app.servicios.usuarios import (
    crear_operador as crear_operador_servicio,
)
from main import app

RUTA_CREAR_OPERADOR = "/api/admin/operadores"
RUTA_ACTIVACION = "/api/autenticacion/activacion-operador"
NOMBRE_COOKIE_SESION = "smart_parking_session"
CONTRASENA_ADMIN = "Contrasena segura SP031 123"
CONTRASENA_OPERADOR = "Operador inicial SP031 123"
CONTRASENA_NUEVA = "Nueva clave SP031 456"


class TransporteFalso:
    """Captura MIME solo en memoria y puede simular rechazo del proveedor."""

    def __init__(self) -> None:
        self.mensajes: list[EmailMessage] = []
        self.error: ErrorCorreo | None = None

    def enviar(self, mensaje: EmailMessage) -> None:
        if self.error is not None:
            raise self.error
        self.mensajes.append(mensaje)


def correo_de_prueba() -> str:
    return f"sp031-test-{uuid4().hex}@example.com"


def settings_de_prueba(**overrides: Any) -> Settings:
    valores: dict[str, Any] = {
        "database_host": "localhost",
        "database_port": 5432,
        "database_name": "unused",
        "database_user": "unused",
        "database_password": SecretStr("test-db-password"),
        "app_environment": "development",
        "app_public_url": "https://parking.example",
        "correo_transporte": "smtp",
        "smtp_host": "smtp.test.invalid",
        "smtp_port": "465",
        "smtp_username": "smtp-user",
        "smtp_password": SecretStr("smtp-secret-test-only"),
        "smtp_from_email": "no-reply@example.com",
        "smtp_from_name": "Smart Parking",
        "smtp_security": "ssl",
        "smtp_timeout_seconds": "10",
        "activacion_reenvio_cooldown_segundos": 60,
        "activation_token_ttl_hours": 24,
        "activation_challenge_ttl_minutes": 15,
    }
    valores.update(overrides)
    return Settings(**valores)


@pytest.fixture
def client(database_url: URL) -> Generator[TestClient]:
    engine = create_engine(database_url, pool_pre_ping=True)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[Session]:
        session = session_factory()
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
        engine.dispose()


def crear_admin_autenticado(db: Session) -> str:
    resultado = crear_admin(
        db,
        nombre="Katherine",
        apellido_paterno="Johnson",
        apellido_materno="Coleman",
        correo=correo_de_prueba(),
        contrasena=CONTRASENA_ADMIN,
        confirmacion_contrasena=CONTRASENA_ADMIN,
    )
    usuario = resultado.usuario
    usuario.correo_verificado = True
    usuario.debe_cambiar_contrasena = False
    db.commit()
    db.rollback()

    token = f"admin-session-sp031-{uuid4().hex}"
    ahora = datetime.now(UTC)
    db.add(
        Sesion(
            usuario_id=usuario.id,
            token_hash=hash_token_sesion(token),
            expira_en=ahora + timedelta(minutes=30),
            creado_en=ahora,
        )
    )
    db.commit()
    db.rollback()
    return token


def crear_invitacion(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    correo: str | None = None,
) -> tuple[Usuario, str, TransporteFalso, Settings, str]:
    settings = settings_de_prueba()
    transporte = TransporteFalso()
    monkeypatch.setattr("app.api.rutas.operadores.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.api.rutas.operadores.crear_transporte_correo",
        lambda _settings: transporte,
    )
    token_admin = crear_admin_autenticado(db)
    correo_operador = correo or correo_de_prueba()

    respuesta = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json={
            "nombre": "Grace",
            "apellido_paterno": "Hopper",
            "apellido_materno": "Murray",
            "correo": correo_operador,
        },
        cookies={NOMBRE_COOKIE_SESION: token_admin},
    )
    assert respuesta.status_code == 201
    assert len(transporte.mensajes) == 1
    mensaje = transporte.mensajes[0]
    cuerpo = mensaje.get_body(preferencelist=("plain",))
    assert cuerpo is not None
    enlace = next(
        linea
        for linea in cuerpo.get_content().splitlines()
        if "/activar-cuenta?token=" in linea
    )
    token_invitacion = parse_qs(urlsplit(enlace).query)["token"][0]

    monkeypatch.setattr(
        "app.api.rutas.activaciones_operador.get_settings",
        lambda: settings,
    )
    operador = db.scalar(select(Usuario).where(Usuario.correo == correo_operador))
    assert operador is not None
    return operador, token_invitacion, transporte, settings, token_admin


def crear_invitacion_admin(db: Session) -> tuple[Usuario, str]:
    tokens: list[str] = []
    resultado = crear_admin_pendiente(
        db,
        nombre="Katherine",
        apellido_paterno="Johnson",
        apellido_materno="Coleman",
        correo=correo_de_prueba(),
        entregar_invitacion=lambda _usuario, token: tokens.append(token),
        duracion_token_horas=24,
    )
    assert len(tokens) == 1
    return resultado.usuario, tokens[0]


def intercambiar_enlace(client: TestClient, token: str):
    return client.post(
        f"{RUTA_ACTIVACION}/enlace",
        json={"token": token},
    )


def valor_cookie(respuesta, nombre: str) -> str:
    cookies = SimpleCookie()
    cookies.load(respuesta.headers["set-cookie"])
    return cookies[nombre].value


def cuerpo_creacion_operador(correo: str) -> dict[str, str]:
    """Devuelve una solicitud valida y sintetica de alta OPERADOR."""

    return {
        "nombre": "Grace",
        "apellido_paterno": "Hopper",
        "apellido_materno": "Murray",
        "correo": correo,
    }


def exigir_estado_http(respuesta: Any, esperado: int, accion: str) -> None:
    """Falla con un mensaje seguro que no imprime cuerpos ni credenciales."""

    if respuesta.status_code != esperado:
        pytest.fail(
            f"{accion}: se esperaba HTTP {esperado}, se obtuvo {respuesta.status_code}."
        )


def exigir_sin_exposicion(
    superficies: Iterable[str],
    valores_sensibles: Iterable[str | None],
) -> None:
    """Impide que una asercion fallida imprima el valor filtrado."""

    valores = [valor for valor in valores_sensibles if valor]
    for superficie in superficies:
        if any(valor in superficie for valor in valores):
            pytest.fail("Se encontro material sensible en una salida publica o log.")


def encabezados_sin_cookie(respuesta: Any) -> str:
    """Serializa solo encabezados que no transportan cookies intencionales."""

    return "\n".join(
        f"{nombre}: {valor}"
        for nombre, valor in respuesta.headers.items()
        if nombre.lower() != "set-cookie"
    )


def token_del_ultimo_mensaje(transporte: TransporteFalso) -> str:
    """Extrae en memoria el unico token del ultimo correo de invitacion."""

    if not transporte.mensajes:
        pytest.fail("No se capturo el correo sintetico esperado.")
    cuerpo = transporte.mensajes[-1].get_body(preferencelist=("plain",))
    if cuerpo is None:
        pytest.fail("El correo sintetico no contiene texto plano.")
    enlaces = [
        linea
        for linea in cuerpo.get_content().splitlines()
        if "/activar-cuenta?token=" in linea
    ]
    if len(enlaces) != 1:
        pytest.fail(
            "El correo sintetico no contiene exactamente un enlace de activacion."
        )
    return parse_qs(urlsplit(enlaces[0]).query)["token"][0]


def envolver_con_barrera(
    funcion: Callable[..., Any],
    barrera: Barrier,
) -> Callable[..., Any]:
    """Alinea dos solicitudes inmediatamente antes de la operacion transaccional."""

    def ejecutar(*args: Any, **kwargs: Any) -> Any:
        barrera.wait(timeout=10)
        return funcion(*args, **kwargs)

    return ejecutar


def activar_operador_para_prueba(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    correo: str | None = None,
) -> Usuario:
    """Completa la invitacion sintetica y devuelve la cuenta persistida."""

    operador, token, _transporte, _settings, _admin = crear_invitacion(
        db,
        client,
        monkeypatch,
        correo=correo,
    )
    canje = intercambiar_enlace(client, token)
    exigir_estado_http(canje, 204, "Canje de invitacion sintetica")
    desafio = valor_cookie(canje, NOMBRE_COOKIE_DESAFIO)
    completar = solicitar_con_cookies(
        client,
        "POST",
        f"{RUTA_ACTIVACION}/completar",
        json={"nueva_contrasena": CONTRASENA_OPERADOR},
        cookies={NOMBRE_COOKIE_DESAFIO: desafio},
    )
    exigir_estado_http(completar, 200, "Completar invitacion sintetica")

    db.rollback()
    db.expire_all()
    usuario = db.get(Usuario, operador.id)
    if (
        usuario is None
        or not usuario.correo_verificado
        or usuario.contrasena_hash is None
    ):
        pytest.fail("La cuenta sintetica no alcanzo el estado activo esperado.")
    return usuario


def test_creacion_canje_completado_y_login_normal_sin_sesion_en_activacion(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operador, token, _transporte, _settings, _admin = crear_invitacion(
        db,
        client,
        monkeypatch,
    )
    assert operador.contrasena_hash is None
    assert operador.correo_verificado is False

    login_pendiente = client.post(
        "/api/autenticacion/login",
        json={"correo": operador.correo, "contrasena": CONTRASENA_NUEVA},
    )
    assert login_pendiente.status_code == 401
    assert login_pendiente.json() == {"detail": "Credenciales invalidas"}
    assert "set-cookie" not in login_pendiente.headers

    canje = intercambiar_enlace(client, token)
    assert canje.status_code == 204
    assert canje.headers["cache-control"] == "no-store"
    assert canje.headers["referrer-policy"] == "no-referrer"
    cookie_desafio = valor_cookie(canje, NOMBRE_COOKIE_DESAFIO)
    cookie = SimpleCookie()
    cookie.load(canje.headers["set-cookie"])
    assert cookie[NOMBRE_COOKIE_DESAFIO]["httponly"] is True
    assert cookie[NOMBRE_COOKIE_DESAFIO]["samesite"].lower() == "lax"
    assert cookie[NOMBRE_COOKIE_DESAFIO]["path"] == RUTA_ACTIVACION
    assert cookie[NOMBRE_COOKIE_DESAFIO]["max-age"] == "900"

    db.rollback()
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador.id)
    )
    assert activacion is not None
    assert activacion.consumido_en is None
    assert activacion.desafio_hash == hash_token_activacion(cookie_desafio)
    assert activacion.desafio_hash is not None
    assert cookie_desafio not in activacion.desafio_hash
    assert activacion.codigo_hash is None

    estado = solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: cookie_desafio},
    )
    assert estado.status_code == 200
    assert estado.headers["cache-control"] == "no-store"
    assert estado.headers["referrer-policy"] == "no-referrer"
    assert estado.json() == {"valido": True}

    completar = solicitar_con_cookies(
        client,
        "POST",
        f"{RUTA_ACTIVACION}/completar",
        json={"nueva_contrasena": CONTRASENA_NUEVA},
        cookies={NOMBRE_COOKIE_DESAFIO: cookie_desafio},
    )
    assert completar.status_code == 200
    assert completar.json() == {"estado": "cuenta_activada"}
    assert completar.headers["cache-control"] == "no-store"
    assert "smart_parking_session" not in completar.headers.get("set-cookie", "")
    cookie_expirada = SimpleCookie()
    cookie_expirada.load(completar.headers["set-cookie"])
    assert cookie_expirada[NOMBRE_COOKIE_DESAFIO].value == ""
    assert cookie_expirada[NOMBRE_COOKIE_DESAFIO]["path"] == RUTA_ACTIVACION
    assert cookie_expirada[NOMBRE_COOKIE_DESAFIO]["max-age"] == "0"

    db.rollback()
    usuario = db.get(Usuario, operador.id)
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador.id)
    )
    assert usuario is not None
    assert usuario.correo_verificado is True
    assert usuario.debe_cambiar_contrasena is False
    assert usuario.contrasena_hash is not None
    assert verificar_contrasena(CONTRASENA_NUEVA, usuario.contrasena_hash)
    assert activacion is not None
    assert activacion.consumido_en is not None
    assert activacion.desafio_hash is None
    assert activacion.desafio_expira_en is None
    assert db.scalar(select(Sesion.id).where(Sesion.usuario_id == operador.id)) is None
    assert client.get("/api/autenticacion/me").status_code == 401
    assert solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: cookie_desafio},
    ).json() == {"valido": False}

    login = client.post(
        "/api/autenticacion/login",
        json={"correo": operador.correo, "contrasena": CONTRASENA_NUEVA},
    )
    assert login.status_code == 200
    assert login.json() == {
        "estado": "credenciales_validas",
        "rol": RolUsuario.OPERADOR.value,
    }


def test_admin_pendiente_usa_el_mismo_enlace_challenge_y_login_normal(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_de_prueba()
    monkeypatch.setattr(
        "app.api.rutas.activaciones_operador.get_settings",
        lambda: settings,
    )
    admin, token = crear_invitacion_admin(db)

    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == admin.id)
    )
    assert activacion is not None
    assert activacion.codigo_hash is None
    assert activacion.token_hash == hash_token_activacion(token)
    assert admin.rol == RolUsuario.ADMIN.value
    assert admin.contrasena_hash is None
    assert admin.correo_verificado is False
    assert admin.debe_cambiar_contrasena is False

    login_pendiente = client.post(
        "/api/autenticacion/login",
        json={"correo": admin.correo, "contrasena": CONTRASENA_NUEVA},
    )
    assert login_pendiente.status_code == 401
    assert login_pendiente.json() == {"detail": "Credenciales invalidas"}
    assert "set-cookie" not in login_pendiente.headers
    assert client.get("/api/autenticacion/me").status_code == 401

    canje = intercambiar_enlace(client, token)
    assert canje.status_code == 204
    desafio = valor_cookie(canje, NOMBRE_COOKIE_DESAFIO)
    extra_rol = client.post(
        f"{RUTA_ACTIVACION}/enlace",
        json={"token": token, "rol": RolUsuario.OPERADOR.value},
    )
    assert extra_rol.status_code == 422

    completar = solicitar_con_cookies(
        client,
        "POST",
        f"{RUTA_ACTIVACION}/completar",
        json={"nueva_contrasena": CONTRASENA_NUEVA},
        cookies={NOMBRE_COOKIE_DESAFIO: desafio},
    )
    assert completar.status_code == 200
    assert "smart_parking_session" not in completar.headers.get("set-cookie", "")

    db.rollback()
    usuario = db.get(Usuario, admin.id)
    activacion_actual = db.get(ActivacionCuenta, activacion.id)
    assert usuario is not None
    assert usuario.rol == RolUsuario.ADMIN.value
    assert usuario.correo_verificado is True
    assert usuario.debe_cambiar_contrasena is False
    assert usuario.contrasena_hash is not None
    assert verificar_contrasena(CONTRASENA_NUEVA, usuario.contrasena_hash)
    assert activacion_actual is not None
    assert activacion_actual.consumido_en is not None
    assert activacion_actual.desafio_hash is None
    assert db.scalar(select(Sesion.id).where(Sesion.usuario_id == admin.id)) is None

    login = client.post(
        "/api/autenticacion/login",
        json={"correo": admin.correo, "contrasena": CONTRASENA_NUEVA},
    )
    assert login.status_code == 200
    assert login.json() == {
        "estado": "credenciales_validas",
        "rol": RolUsuario.ADMIN.value,
    }


def test_desafio_viejo_no_funciona_y_password_policy_es_servidor_autoritativo(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _operador, token, _transporte, _settings, _admin = crear_invitacion(
        db,
        client,
        monkeypatch,
    )
    primer_canje = intercambiar_enlace(client, token)
    primer_desafio = valor_cookie(primer_canje, NOMBRE_COOKIE_DESAFIO)
    segundo_canje = intercambiar_enlace(client, token)
    segundo_desafio = valor_cookie(segundo_canje, NOMBRE_COOKIE_DESAFIO)
    assert primer_desafio != segundo_desafio

    estado_viejo = solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: primer_desafio},
    )
    estado_actual = solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: segundo_desafio},
    )
    assert estado_viejo.json() == {"valido": False}
    assert estado_actual.json() == {"valido": True}

    respuesta = solicitar_con_cookies(
        client,
        "POST",
        f"{RUTA_ACTIVACION}/completar",
        json={"nueva_contrasena": "solo minusculas 123"},
        cookies={NOMBRE_COOKIE_DESAFIO: segundo_desafio},
    )
    assert respuesta.status_code == 422
    assert "solo minusculas 123" not in respuesta.text
    assert solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: segundo_desafio},
    ).json() == {"valido": True}


def test_desafio_vencido_no_activa_y_el_enlace_sigue_canjeable(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operador, token, _transporte, _settings, _admin = crear_invitacion(
        db,
        client,
        monkeypatch,
    )
    primer_canje = intercambiar_enlace(client, token)
    desafio_vencido = valor_cookie(primer_canje, NOMBRE_COOKIE_DESAFIO)

    db.rollback()
    db.expire_all()
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador.id)
    )
    assert activacion is not None
    activacion.desafio_expira_en = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    db.rollback()

    estado = solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: desafio_vencido},
    )
    assert estado.status_code == 200
    assert estado.json() == {"valido": False}
    completar = solicitar_con_cookies(
        client,
        "POST",
        f"{RUTA_ACTIVACION}/completar",
        json={"nueva_contrasena": CONTRASENA_NUEVA},
        cookies={NOMBRE_COOKIE_DESAFIO: desafio_vencido},
    )
    assert completar.status_code == 404
    assert completar.json() == {"detail": "Activación no disponible"}

    db.rollback()
    db.expire_all()
    usuario = db.get(Usuario, operador.id)
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador.id)
    )
    assert usuario is not None and usuario.contrasena_hash is None
    assert usuario.correo_verificado is False
    assert activacion is not None and activacion.consumido_en is None

    segundo_canje = intercambiar_enlace(client, token)
    assert segundo_canje.status_code == 204
    desafio_nuevo = valor_cookie(segundo_canje, NOMBRE_COOKIE_DESAFIO)
    estado_nuevo = solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: desafio_nuevo},
    )
    assert estado_nuevo.json() == {"valido": True}


def test_enlace_vencido_no_crea_desafio_ni_cambia_la_cuenta(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operador, token, _transporte, _settings, _admin = crear_invitacion(
        db,
        client,
        monkeypatch,
    )
    db.rollback()
    db.expire_all()
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador.id)
    )
    assert activacion is not None
    activacion.expira_en = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    db.rollback()

    canje = intercambiar_enlace(client, token)
    assert canje.status_code == 404
    assert canje.json() == {"detail": "Activación no disponible"}
    assert canje.headers["cache-control"] == "no-store"
    assert canje.headers["referrer-policy"] == "no-referrer"
    assert "set-cookie" not in canje.headers

    db.rollback()
    db.expire_all()
    usuario = db.get(Usuario, operador.id)
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador.id)
    )
    assert usuario is not None and usuario.contrasena_hash is None
    assert usuario.correo_verificado is False
    assert activacion is not None and activacion.consumido_en is None
    assert activacion.desafio_hash is None


def test_reenvio_fallido_preserva_invitacion_y_desafio_y_respeta_cooldown(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operador, token_anterior, transporte, settings, token_admin = crear_invitacion(
        db,
        client,
        monkeypatch,
    )
    transporte.mensajes.clear()
    canje = intercambiar_enlace(client, token_anterior)
    desafio_anterior = valor_cookie(canje, NOMBRE_COOKIE_DESAFIO)

    db.rollback()
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador.id)
    )
    assert activacion is not None
    activacion.creado_en = datetime.now(UTC) - timedelta(minutes=2)
    db.commit()
    db.rollback()

    transporte.error = ErrorEnvioCorreo()
    ruta_reenvio = f"{RUTA_CREAR_OPERADOR}/{operador.id}/reenviar-invitacion"
    fallido = solicitar_con_cookies(
        client, "POST", ruta_reenvio, cookies={NOMBRE_COOKIE_SESION: token_admin}
    )
    assert fallido.status_code == 503
    assert fallido.headers["cache-control"] == "no-store"
    assert fallido.json() == {
        "detail": "Servicio de correo temporalmente no disponible"
    }

    db.rollback()
    db.expire_all()
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador.id)
    )
    assert activacion is not None
    assert activacion.consumido_en is None
    assert activacion.desafio_hash == hash_token_activacion(desafio_anterior)
    assert activacion.ultimo_reenvio_en is not None

    cooldown = solicitar_con_cookies(
        client, "POST", ruta_reenvio, cookies={NOMBRE_COOKIE_SESION: token_admin}
    )
    assert cooldown.status_code == 429
    assert transporte.mensajes == []

    activacion.ultimo_reenvio_en = datetime.now(UTC) - timedelta(minutes=2)
    db.commit()
    db.rollback()
    transporte.error = None
    reenviado = solicitar_con_cookies(
        client, "POST", ruta_reenvio, cookies={NOMBRE_COOKIE_SESION: token_admin}
    )
    assert reenviado.status_code == 200
    assert reenviado.json() == {"estado": "invitacion_enviada"}
    assert len(transporte.mensajes) == 1

    cuerpo = transporte.mensajes[0].get_body(preferencelist=("plain",))
    assert cuerpo is not None
    enlace_nuevo = next(
        linea
        for linea in cuerpo.get_content().splitlines()
        if "/activar-cuenta?token=" in linea
    )
    token_nuevo = parse_qs(urlsplit(enlace_nuevo).query)["token"][0]
    assert token_nuevo != token_anterior
    db.rollback()
    db.expire_all()
    activaciones = db.scalars(
        select(ActivacionCuenta)
        .where(ActivacionCuenta.usuario_id == operador.id)
        .order_by(ActivacionCuenta.id)
    ).all()
    assert len(activaciones) == 2
    assert activaciones[0].consumido_en is not None
    assert activaciones[0].desafio_hash is None
    assert activaciones[1].codigo_hash is None
    assert activaciones[1].token_hash == hash_token_activacion(token_nuevo)
    assert solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: desafio_anterior},
    ).json() == {"valido": False}
    assert intercambiar_enlace(client, token_anterior).status_code == 404
    assert settings.activation_token_ttl_hours == 24


def test_commit_final_fallido_conserva_invitacion_anterior_y_oculta_candidata(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operador, token_anterior, transporte, _settings, token_admin = crear_invitacion(
        db,
        client,
        monkeypatch,
    )
    transporte.mensajes.clear()
    desafio_anterior = valor_cookie(
        intercambiar_enlace(client, token_anterior),
        NOMBRE_COOKIE_DESAFIO,
    )
    db.rollback()
    db.expire_all()
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador.id)
    )
    assert activacion is not None
    activacion.creado_en = datetime.now(UTC) - timedelta(minutes=2)
    db.commit()
    db.rollback()

    cantidad_commits = 0

    def fallar_commit_final(_sesion: Session) -> None:
        nonlocal cantidad_commits
        cantidad_commits += 1
        if cantidad_commits == 2:
            raise SQLAlchemyError("fallo sintetico de commit")

    event.listen(Session, "before_commit", fallar_commit_final)
    try:
        respuesta = solicitar_con_cookies(
            client,
            "POST",
            f"{RUTA_CREAR_OPERADOR}/{operador.id}/reenviar-invitacion",
            cookies={NOMBRE_COOKIE_SESION: token_admin},
        )
    finally:
        event.remove(Session, "before_commit", fallar_commit_final)

    assert cantidad_commits == 2
    assert respuesta.status_code == 500
    assert respuesta.json() == {"detail": "Error interno"}
    assert "fallo sintetico" not in respuesta.text
    assert len(transporte.mensajes) == 1
    cuerpo = transporte.mensajes[0].get_body(preferencelist=("plain",))
    assert cuerpo is not None
    enlace_candidato = next(
        linea
        for linea in cuerpo.get_content().splitlines()
        if "/activar-cuenta?token=" in linea
    )
    token_candidato = parse_qs(urlsplit(enlace_candidato).query)["token"][0]
    assert token_candidato != token_anterior
    assert token_candidato not in respuesta.text

    db.rollback()
    db.expire_all()
    activaciones = db.scalars(
        select(ActivacionCuenta)
        .where(ActivacionCuenta.usuario_id == operador.id)
        .order_by(ActivacionCuenta.id)
    ).all()
    assert len(activaciones) == 1
    assert activaciones[0].token_hash == hash_token_activacion(token_anterior)
    assert activaciones[0].consumido_en is None
    assert activaciones[0].desafio_hash == hash_token_activacion(desafio_anterior)
    assert activaciones[0].ultimo_reenvio_en is not None
    assert solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: desafio_anterior},
    ).json() == {"valido": True}

    cooldown = solicitar_con_cookies(
        client,
        "POST",
        f"{RUTA_CREAR_OPERADOR}/{operador.id}/reenviar-invitacion",
        cookies={NOMBRE_COOKIE_SESION: token_admin},
    )
    assert cooldown.status_code == 429
    assert len(transporte.mensajes) == 1


def test_desactivar_y_reactivar_no_reviven_el_enlace_anterior(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operador, token_anterior, transporte, _settings, token_admin = crear_invitacion(
        db,
        client,
        monkeypatch,
    )
    transporte.mensajes.clear()
    desafio = valor_cookie(
        intercambiar_enlace(client, token_anterior),
        NOMBRE_COOKIE_DESAFIO,
    )
    ruta_admin = f"{RUTA_CREAR_OPERADOR}/{operador.id}"
    desactivar = solicitar_con_cookies(
        client,
        "POST",
        f"{ruta_admin}/desactivar",
        cookies={NOMBRE_COOKIE_SESION: token_admin},
    )
    reactivar = solicitar_con_cookies(
        client,
        "POST",
        f"{ruta_admin}/reactivar",
        cookies={NOMBRE_COOKIE_SESION: token_admin},
    )
    assert desactivar.status_code == reactivar.status_code == 200

    db.rollback()
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador.id)
    )
    assert activacion is not None
    assert activacion.consumido_en is not None
    assert activacion.desafio_hash is None
    assert solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: desafio},
    ).json() == {"valido": False}
    assert intercambiar_enlace(client, token_anterior).status_code == 404

    activacion.creado_en = datetime.now(UTC) - timedelta(minutes=2)
    activacion.ultimo_reenvio_en = activacion.creado_en
    db.commit()
    db.rollback()
    ruta_reenvio = f"{RUTA_CREAR_OPERADOR}/{operador.id}/reenviar-invitacion"
    respuesta = solicitar_con_cookies(
        client, "POST", ruta_reenvio, cookies={NOMBRE_COOKIE_SESION: token_admin}
    )
    assert respuesta.status_code == 200
    assert len(transporte.mensajes) == 1


def test_dos_completados_simultaneos_consumen_un_solo_desafio(
    db: Session,
    database_url: URL,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operador, token_enlace, _transporte, _settings, _admin = crear_invitacion(
        db,
        client,
        monkeypatch,
    )
    desafio = valor_cookie(
        intercambiar_enlace(client, token_enlace),
        NOMBRE_COOKIE_DESAFIO,
    )
    engine = create_engine(database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def completar() -> str:
        with session_factory() as sesion:
            try:
                completar_activacion_operador(
                    sesion,
                    token_desafio=desafio,
                    nueva_contrasena=CONTRASENA_OPERADOR,
                )
            except ActivacionOperadorNoDisponible:
                return "no_disponible"
            return "activada"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _indice: completar(), range(2)))
    finally:
        engine.dispose()

    assert sorted(resultados) == ["activada", "no_disponible"]
    db.rollback()
    usuario = db.get(Usuario, operador.id)
    assert usuario is not None and usuario.correo_verificado is True
    assert usuario.contrasena_hash is not None
    assert verificar_contrasena(CONTRASENA_OPERADOR, usuario.contrasena_hash)


def test_duplicados_admin_y_correo_normalizado_no_envian_invitaciones_extra(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_de_prueba()
    transporte = TransporteFalso()
    monkeypatch.setattr("app.api.rutas.operadores.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.api.rutas.operadores.crear_transporte_correo",
        lambda _settings: transporte,
    )
    token_admin = crear_admin_autenticado(db)
    sesion_admin = db.scalar(
        select(Sesion).where(Sesion.token_hash == hash_token_sesion(token_admin))
    )
    if sesion_admin is None:
        pytest.fail("No se encontro la sesion sintetica ADMIN.")
    admin = db.get(Usuario, sesion_admin.usuario_id)
    if admin is None:
        pytest.fail("No se encontro la cuenta sintetica ADMIN.")

    duplicado_admin = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=cuerpo_creacion_operador(admin.correo),
        cookies={NOMBRE_COOKIE_SESION: token_admin},
    )
    exigir_estado_http(duplicado_admin, 409, "Correo ya asignado a ADMIN")
    if transporte.mensajes:
        pytest.fail("El correo duplicado de ADMIN produjo un envio.")

    correo_original = f"SP031.Dupe-{uuid4().hex}@example.com"
    correo_normalizado = correo_original.casefold()
    primera_alta = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=cuerpo_creacion_operador(correo_original),
        cookies={NOMBRE_COOKIE_SESION: token_admin},
    )
    exigir_estado_http(primera_alta, 201, "Alta sintetica inicial")
    duplicado_normalizado = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=cuerpo_creacion_operador(f"  {correo_normalizado.upper()}  "),
        cookies={NOMBRE_COOKIE_SESION: token_admin},
    )
    exigir_estado_http(
        duplicado_normalizado, 409, "Correo equivalente por mayusculas y espacios"
    )

    db.rollback()
    cantidad_usuarios = db.scalar(
        select(func.count())
        .select_from(Usuario)
        .where(Usuario.correo == correo_normalizado)
    )
    operador = db.scalar(select(Usuario).where(Usuario.correo == correo_normalizado))
    if operador is None:
        cantidad_activaciones = 0
    else:
        cantidad_activaciones = db.scalar(
            select(func.count())
            .select_from(ActivacionCuenta)
            .where(ActivacionCuenta.usuario_id == operador.id)
        )
    if cantidad_usuarios != 1 or cantidad_activaciones != 1:
        pytest.fail(
            "Los duplicados alteraron el numero esperado de usuarios o invitaciones."
        )
    if len(transporte.mensajes) != 1:
        pytest.fail("Los duplicados produjeron un correo adicional.")


def test_creacion_rechaza_campos_controlados_y_limites_sin_reflejar_entradas(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_de_prueba()
    transporte = TransporteFalso()
    monkeypatch.setattr("app.api.rutas.operadores.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.api.rutas.operadores.crear_transporte_correo",
        lambda _settings: transporte,
    )
    token_admin = crear_admin_autenticado(db)
    correo_sintetico = f"sp031-inyeccion-{uuid4().hex}@example.com"
    solicitud = cuerpo_creacion_operador(correo_sintetico)
    campos_controlados: dict[str, object] = {
        "rol": "ADMIN",
        "id": 900001,
        "usuario_id": 900002,
        "esta_activo": False,
        "correo_verificado": True,
        "debe_cambiar_contrasena": True,
        "password": "SP031 synthetic password value",
        "contrasena": "SP031 synthetic credential value",
        "password_hash": "synthetic-password-hash",
        "contrasena_hash": "synthetic-password-hash-2",
    }
    respuestas = []
    valores_inyectados: list[str] = []
    for campo, valor in campos_controlados.items():
        respuesta = solicitar_con_cookies(
            client,
            "POST",
            RUTA_CREAR_OPERADOR,
            json={**solicitud, campo: valor},
            cookies={NOMBRE_COOKIE_SESION: token_admin},
        )
        exigir_estado_http(respuesta, 422, f"Campo no permitido {campo}")
        respuestas.append(respuesta.text)
        valores_inyectados.append(str(valor))

    solicitudes_invalidas: list[dict[str, object]] = [
        {**solicitud, "nombre": " "},
        {**solicitud, "apellido_paterno": " "},
        {**solicitud, "nombre": "N" * 101},
        {**solicitud, "correo": "C" * 321},
        {**solicitud, "correo": "not-an-email"},
        {
            clave: valor
            for clave, valor in solicitud.items()
            if clave != "apellido_materno"
        },
    ]
    for solicitud_invalida in solicitudes_invalidas:
        respuesta = solicitar_con_cookies(
            client,
            "POST",
            RUTA_CREAR_OPERADOR,
            json=solicitud_invalida,
            cookies={NOMBRE_COOKIE_SESION: token_admin},
        )
        exigir_estado_http(
            respuesta, 422, "Identidad sintetica invalida o fuera de limites"
        )
        respuestas.append(respuesta.text)

    exigir_sin_exposicion(respuestas, valores_inyectados)
    db.rollback()
    operador = db.scalar(select(Usuario).where(Usuario.correo == correo_sintetico))
    if operador is not None or transporte.mensajes:
        pytest.fail("Una solicitud rechazada dejo una cuenta o envio de invitacion.")


def test_creacion_concurrente_del_mismo_correo_normalizado_es_atomica(
    db: Session,
    client: TestClient,
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_de_prueba()
    transporte = TransporteFalso()
    monkeypatch.setattr("app.api.rutas.operadores.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.api.rutas.operadores.crear_transporte_correo",
        lambda _settings: transporte,
    )
    token_admin = crear_admin_autenticado(db)
    correo = f"sp031-race-{uuid4().hex}@example.com"
    barrera = Barrier(2)
    monkeypatch.setattr(
        "app.api.rutas.operadores.crear_operador",
        envolver_con_barrera(crear_operador_servicio, barrera),
    )

    def enviar_alta(_indice: int) -> int:
        respuesta = solicitar_con_cookies(
            client,
            "POST",
            RUTA_CREAR_OPERADOR,
            json=cuerpo_creacion_operador(f" {correo.upper()} "),
            cookies={NOMBRE_COOKIE_SESION: token_admin},
        )
        return respuesta.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        resultados = list(executor.map(enviar_alta, range(2)))
    if sorted(resultados) != [201, 409]:
        pytest.fail(
            f"La carrera de alta produjo estados HTTP inesperados: {sorted(resultados)}"
        )

    db.rollback()
    db.expire_all()
    usuario = db.scalar(select(Usuario).where(Usuario.correo == correo))
    if usuario is None:
        activaciones = []
    else:
        activaciones = db.scalars(
            select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == usuario.id)
        ).all()
    if (
        usuario is None
        or usuario.rol != RolUsuario.OPERADOR.value
        or len(activaciones) != 1
        or len(transporte.mensajes) != 1
    ):
        pytest.fail(
            "La carrera no dejo exactamente una cuenta pendiente y una invitacion."
        )


def test_activacion_rechaza_desafio_ausente_alterado_y_replays_y_fija_la_cuenta(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operador_a, token_a, _transporte_a, _settings_a, _admin_a = crear_invitacion(
        db,
        client,
        monkeypatch,
    )
    db.rollback()
    operador_b, _token_b, _transporte_b, _settings_b, _admin_b = crear_invitacion(
        db,
        client,
        monkeypatch,
    )

    token_malformado = intercambiar_enlace(client, "x")
    exigir_estado_http(token_malformado, 422, "Token de forma invalida")
    token_aleatorio = intercambiar_enlace(client, f"aleatorio-{uuid4().hex}-invalido")
    exigir_estado_http(token_aleatorio, 404, "Token aleatorio inexistente")
    for respuesta in (token_malformado, token_aleatorio):
        if "set-cookie" in respuesta.headers:
            pytest.fail("Un enlace no valido establecio una cookie de desafio.")

    falta_desafio = solicitar_con_cookies(
        client,
        "POST",
        f"{RUTA_ACTIVACION}/completar",
        json={"nueva_contrasena": CONTRASENA_NUEVA},
        cookies={NOMBRE_COOKIE_DESAFIO: ""},
    )
    exigir_estado_http(falta_desafio, 404, "Completar sin desafio")
    desafio_ausente = solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: ""},
    )
    exigir_estado_http(desafio_ausente, 200, "Consultar desafio ausente")
    if desafio_ausente.json() != {"valido": False}:
        pytest.fail("La consulta de un desafio ausente no fue opaca.")

    primer_canje = intercambiar_enlace(client, token_a)
    exigir_estado_http(primer_canje, 204, "Primer canje del enlace actual")
    desafio_anterior = valor_cookie(primer_canje, NOMBRE_COOKIE_DESAFIO)
    desafio_modificado = solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: f"{desafio_anterior}x"},
    )
    if desafio_modificado.json() != {"valido": False}:
        pytest.fail("Una cookie de desafio modificada se acepto.")
    desafio_modificado_completar = solicitar_con_cookies(
        client,
        "POST",
        f"{RUTA_ACTIVACION}/completar",
        json={"nueva_contrasena": CONTRASENA_NUEVA},
        cookies={NOMBRE_COOKIE_DESAFIO: f"{desafio_anterior}x"},
    )
    exigir_estado_http(
        desafio_modificado_completar, 404, "Completar con desafio modificado"
    )

    segundo_canje = intercambiar_enlace(client, token_a)
    exigir_estado_http(segundo_canje, 204, "Rotar el desafio del enlace vigente")
    desafio_actual = valor_cookie(segundo_canje, NOMBRE_COOKIE_DESAFIO)
    anterior = solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: desafio_anterior},
    )
    if anterior.json() != {"valido": False}:
        pytest.fail("El desafio anterior siguio vigente tras la rotacion.")

    intento_id_inyectado = solicitar_con_cookies(
        client,
        "POST",
        f"{RUTA_ACTIVACION}/completar?usuario_id={operador_b.id}&rol=ADMIN",
        json={
            "nueva_contrasena": CONTRASENA_NUEVA,
            "usuario_id": operador_b.id,
            "correo": operador_b.correo,
            "rol": RolUsuario.ADMIN.value,
            "correo_verificado": True,
            "esta_activo": True,
        },
        cookies={NOMBRE_COOKIE_DESAFIO: desafio_actual},
    )
    exigir_estado_http(
        intento_id_inyectado, 422, "Campos de identidad y estado en activacion"
    )

    completar_a = solicitar_con_cookies(
        client,
        "POST",
        f"{RUTA_ACTIVACION}/completar?usuario_id={operador_b.id}&rol=ADMIN",
        json={"nueva_contrasena": CONTRASENA_NUEVA},
        cookies={NOMBRE_COOKIE_DESAFIO: desafio_actual},
    )
    exigir_estado_http(completar_a, 200, "Completar la cuenta ligada al desafio")
    replay = solicitar_con_cookies(
        client,
        "POST",
        f"{RUTA_ACTIVACION}/completar",
        json={"nueva_contrasena": CONTRASENA_NUEVA},
        cookies={NOMBRE_COOKIE_DESAFIO: desafio_actual},
    )
    exigir_estado_http(replay, 404, "Repetir la finalizacion consumida")
    enlace_repetido = intercambiar_enlace(client, token_a)
    exigir_estado_http(enlace_repetido, 404, "Repetir el enlace consumido")

    db.rollback()
    db.expire_all()
    usuario_a_actual = db.get(Usuario, operador_a.id)
    usuario_b_actual = db.get(Usuario, operador_b.id)
    if (
        usuario_a_actual is None
        or not usuario_a_actual.correo_verificado
        or usuario_a_actual.contrasena_hash is None
        or usuario_b_actual is None
        or usuario_b_actual.correo_verificado
        or usuario_b_actual.contrasena_hash is not None
    ):
        pytest.fail("El desafio afecto una cuenta distinta de su identidad persistida.")
    if "smart_parking_session" in completar_a.headers.get("set-cookie", ""):
        pytest.fail("Completar una activacion creo una sesion autenticada.")


def test_policy_de_contrasena_respeta_limites_y_no_consume_el_desafio_invalido(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _operador, token, _transporte, _settings, _admin = crear_invitacion(
        db,
        client,
        monkeypatch,
    )
    canje = intercambiar_enlace(client, token)
    exigir_estado_http(
        canje, 204, "Canjear invitacion para probar politica de contrasena"
    )
    desafio = valor_cookie(canje, NOMBRE_COOKIE_DESAFIO)
    contrasenas_invalidas = (
        "Abcdef1!x",
        "A" + "a" * 127 + "1",
        "abcdefgh1!",
        "Abcdef1!\nx",
    )
    respuestas = []
    for contrasena in contrasenas_invalidas:
        respuesta = solicitar_con_cookies(
            client,
            "POST",
            f"{RUTA_ACTIVACION}/completar",
            json={"nueva_contrasena": contrasena},
            cookies={NOMBRE_COOKIE_DESAFIO: desafio},
        )
        exigir_estado_http(respuesta, 422, "Contrasena fuera de politica")
        respuestas.append(respuesta.text)
        estado = solicitar_con_cookies(
            client,
            "GET",
            f"{RUTA_ACTIVACION}/desafio",
            cookies={NOMBRE_COOKIE_DESAFIO: desafio},
        )
        if estado.json() != {"valido": True}:
            pytest.fail(
                "Un intento de contrasena invalido consumio el desafio vigente."
            )
    exigir_sin_exposicion(respuestas, contrasenas_invalidas)

    db.rollback()
    operador_minimo, token_minimo, _mail, _config, _admin_token = crear_invitacion(
        db,
        client,
        monkeypatch,
    )
    canje_minimo = intercambiar_enlace(client, token_minimo)
    desafio_minimo = valor_cookie(canje_minimo, NOMBRE_COOKIE_DESAFIO)
    contrasena_minima = "Abcdefg1!x"
    completar_minimo = solicitar_con_cookies(
        client,
        "POST",
        f"{RUTA_ACTIVACION}/completar",
        json={"nueva_contrasena": contrasena_minima},
        cookies={NOMBRE_COOKIE_DESAFIO: desafio_minimo},
    )
    exigir_estado_http(completar_minimo, 200, "Limite minimo valido de contrasena")

    db.rollback()
    db.expire_all()
    cuenta_minima = db.get(Usuario, operador_minimo.id)
    if cuenta_minima is None or not cuenta_minima.correo_verificado:
        pytest.fail("La contrasena minima valida no completo la activacion.")

    db.rollback()
    operador_maximo, token_maximo, _mail, _config, _admin_token = crear_invitacion(
        db,
        client,
        monkeypatch,
    )
    canje_maximo = intercambiar_enlace(client, token_maximo)
    desafio_maximo = valor_cookie(canje_maximo, NOMBRE_COOKIE_DESAFIO)
    contrasena_maxima = "A" + "a" * 126 + "1"
    completar_maximo = solicitar_con_cookies(
        client,
        "POST",
        f"{RUTA_ACTIVACION}/completar",
        json={"nueva_contrasena": contrasena_maxima},
        cookies={NOMBRE_COOKIE_DESAFIO: desafio_maximo},
    )
    exigir_estado_http(completar_maximo, 200, "Limite maximo valido de contrasena")

    db.rollback()
    db.expire_all()
    cuenta_maxima = db.get(Usuario, operador_maximo.id)
    if cuenta_maxima is None or not cuenta_maxima.correo_verificado:
        pytest.fail("La contrasena maxima valida no completo la activacion.")


def test_login_no_acepta_fijacion_y_me_ignora_identidad_inyectada(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operador_a = activar_operador_para_prueba(db, client, monkeypatch)
    db.rollback()
    operador_b = activar_operador_para_prueba(db, client, monkeypatch)
    token_atacante = "sp031-session-token-selected-by-client"
    client.cookies.clear()

    login_a = solicitar_con_cookies(
        client,
        "POST",
        "/api/autenticacion/login",
        json={"correo": operador_a.correo, "contrasena": CONTRASENA_OPERADOR},
        cookies={NOMBRE_COOKIE_SESION: token_atacante},
    )
    exigir_estado_http(login_a, 200, "Login normal de OPERADOR")
    token_sesion_a = valor_cookie(login_a, NOMBRE_COOKIE_SESION)
    if token_sesion_a == token_atacante:
        pytest.fail("El servidor reutilizo el token de sesion escogido por el cliente.")

    sesion_atacante = db.scalar(
        select(Sesion.id).where(Sesion.token_hash == hash_token_sesion(token_atacante))
    )
    sesion_a = db.scalar(
        select(Sesion.id).where(Sesion.token_hash == hash_token_sesion(token_sesion_a))
    )
    if sesion_atacante is not None or sesion_a is None:
        pytest.fail(
            "La persistencia no coincide con la sesion generada por el servidor."
        )

    acceso_token_atacante = solicitar_con_cookies(
        client,
        "GET",
        "/api/autenticacion/me",
        cookies={NOMBRE_COOKIE_SESION: token_atacante},
    )
    exigir_estado_http(
        acceso_token_atacante, 401, "Reutilizar el token elegido por cliente"
    )
    me_a = solicitar_con_cookies(
        client,
        "GET",
        "/api/autenticacion/me?usuario_id=" + str(operador_b.id) + "&rol=ADMIN",
        cookies={NOMBRE_COOKIE_SESION: token_sesion_a},
        headers={"X-Role": "ADMIN", "X-User-ID": str(operador_b.id)},
    )
    exigir_estado_http(me_a, 200, "Consultar identidad con campos falsificados")
    identidad_a = me_a.json().get("usuario", {})
    if (
        identidad_a.get("correo") != operador_a.correo
        or identidad_a.get("rol") != "OPERADOR"
    ):
        pytest.fail(
            "La identidad de /me cambio por parametros o encabezados del cliente."
        )

    settings = settings_de_prueba()
    transporte = TransporteFalso()
    monkeypatch.setattr("app.api.rutas.operadores.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.api.rutas.operadores.crear_transporte_correo",
        lambda _settings: transporte,
    )
    objetivo = f"sp031-forged-admin-{uuid4().hex}@example.com"
    intento_admin = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR + "?usuario_id=1&rol=ADMIN",
        json=cuerpo_creacion_operador(objetivo),
        cookies={NOMBRE_COOKIE_SESION: token_sesion_a},
        headers={"X-Role": "ADMIN", "X-User-ID": "1"},
    )
    exigir_estado_http(
        intento_admin, 401, "OPERADOR intenta usar una ruta ADMIN directa"
    )
    db.rollback()
    if db.scalar(select(Usuario.id).where(Usuario.correo == objetivo)) is not None:
        pytest.fail("Un encabezado ADMIN falsificado creo una cuenta.")
    if transporte.mensajes:
        pytest.fail("Una llamada no autorizada envio una invitacion.")

    login_b = client.post(
        "/api/autenticacion/login",
        json={"correo": operador_b.correo, "contrasena": CONTRASENA_OPERADOR},
    )
    exigir_estado_http(login_b, 200, "Segundo login OPERADOR independiente")
    token_sesion_b = valor_cookie(login_b, NOMBRE_COOKIE_SESION)
    me_b = solicitar_con_cookies(
        client,
        "GET",
        "/api/autenticacion/me",
        cookies={NOMBRE_COOKIE_SESION: token_sesion_b},
    )
    exigir_estado_http(me_b, 200, "Identidad de la segunda cuenta")
    if me_b.json().get("usuario", {}).get("correo") != operador_b.correo:
        pytest.fail("La segunda sesion se resolvio hacia otra cuenta.")


def test_secretos_solo_aparecen_en_canales_de_entrega_autorizados(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    settings = settings_de_prueba()
    transporte = TransporteFalso()
    monkeypatch.setattr("app.api.rutas.operadores.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.api.rutas.operadores.crear_transporte_correo",
        lambda _settings: transporte,
    )
    monkeypatch.setattr(
        "app.api.rutas.activaciones_operador.get_settings",
        lambda: settings,
    )
    token_admin = crear_admin_autenticado(db)
    correo = correo_de_prueba()
    creacion = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=cuerpo_creacion_operador(correo),
        cookies={NOMBRE_COOKIE_SESION: token_admin},
    )
    exigir_estado_http(creacion, 201, "Alta sintetica para comprobar exposicion")
    token_invitacion = token_del_ultimo_mensaje(transporte)
    cuerpo_correo = transporte.mensajes[0].get_body(preferencelist=("plain",))
    if cuerpo_correo is None:
        pytest.fail("El correo sintetico no contiene cuerpo de texto.")
    texto_correo = cuerpo_correo.get_content()
    if texto_correo.count("/activar-cuenta?token=") != 1:
        pytest.fail("La invitacion no contiene exactamente un enlace de activacion.")
    if "codigo" in texto_correo.casefold() or "código" in texto_correo.casefold():
        pytest.fail("La invitacion contiene una referencia a un codigo manual.")
    if CONTRASENA_OPERADOR in texto_correo or CONTRASENA_NUEVA in texto_correo:
        pytest.fail("La invitacion contiene una contrasena de onboarding.")

    operador = db.scalar(select(Usuario).where(Usuario.correo == correo))
    if operador is None:
        pytest.fail("No se encontro la cuenta sintetica para revisar persistencia.")
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador.id)
    )
    if (
        activacion is None
        or activacion.token_hash != hash_token_activacion(token_invitacion)
        or activacion.codigo_hash is not None
    ):
        pytest.fail("La persistencia no conserva solo el hash del enlace token-only.")

    canje = intercambiar_enlace(client, token_invitacion)
    exigir_estado_http(canje, 204, "Canje del enlace para comprobar exposicion")
    desafio = valor_cookie(canje, NOMBRE_COOKIE_DESAFIO)
    db.rollback()
    db.expire_all()
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador.id)
    )
    if activacion is None:
        pytest.fail("No se encontro la invitacion luego del canje.")
    hash_desafio = activacion.desafio_hash
    if hash_desafio != hash_token_activacion(desafio):
        pytest.fail("El desafio no se almaceno como hash.")

    estado = solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: desafio},
    )
    if estado.json() != {"valido": True}:
        pytest.fail("La consulta publica expuso algo distinto del estado booleano.")
    completar = solicitar_con_cookies(
        client,
        "POST",
        f"{RUTA_ACTIVACION}/completar",
        json={"nueva_contrasena": CONTRASENA_OPERADOR},
        cookies={NOMBRE_COOKIE_DESAFIO: desafio},
    )
    exigir_estado_http(completar, 200, "Completar activacion para revisar exposicion")
    db.rollback()
    db.expire_all()
    operador = db.get(Usuario, operador.id)
    if operador is None or operador.contrasena_hash is None:
        pytest.fail("La cuenta activada no contiene el hash esperado.")
    hash_contrasena = operador.contrasena_hash

    login = client.post(
        "/api/autenticacion/login",
        json={"correo": correo, "contrasena": CONTRASENA_OPERADOR},
    )
    exigir_estado_http(login, 200, "Login posterior a activacion")
    token_sesion = valor_cookie(login, NOMBRE_COOKIE_SESION)
    sesion = db.scalar(
        select(Sesion).where(Sesion.token_hash == hash_token_sesion(token_sesion))
    )
    if sesion is None:
        pytest.fail("La sesion valida no se almaceno como hash.")

    superficies = [
        creacion.text,
        encabezados_sin_cookie(creacion),
        canje.text,
        encabezados_sin_cookie(canje),
        estado.text,
        encabezados_sin_cookie(estado),
        completar.text,
        encabezados_sin_cookie(completar),
        login.text,
        encabezados_sin_cookie(login),
        repr(operador),
        repr(activacion),
        repr(sesion),
        caplog.text,
    ]
    secretos = [
        token_admin,
        hash_token_sesion(token_admin),
        token_invitacion,
        hash_token_activacion(token_invitacion),
        desafio,
        hash_desafio,
        CONTRASENA_OPERADOR,
        CONTRASENA_NUEVA,
        hash_contrasena,
        token_sesion,
        hash_token_sesion(token_sesion),
        (
            settings.smtp_password.get_secret_value()
            if settings.smtp_password is not None
            else None
        ),
    ]
    exigir_sin_exposicion(superficies, secretos)

    cookie_desafio = canje.headers.get("set-cookie", "").casefold()
    cookie_sesion = login.headers.get("set-cookie", "").casefold()
    if "httponly" not in cookie_desafio or "samesite=lax" not in cookie_desafio:
        pytest.fail(
            "La cookie de desafio no conserva sus atributos HttpOnly y SameSite."
        )
    if "httponly" not in cookie_sesion or "samesite=lax" not in cookie_sesion:
        pytest.fail(
            "La cookie de sesion no conserva sus atributos HttpOnly y SameSite."
        )


def test_reenvio_concurrente_con_canje_invalida_cualquier_desafio_anterior(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operador, token_anterior, transporte, _settings, token_admin = crear_invitacion(
        db,
        client,
        monkeypatch,
    )
    operador_id = operador.id
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador_id)
    )
    if activacion is None:
        pytest.fail("No se encontro la invitacion sintetica inicial.")
    activacion.creado_en = datetime.now(UTC) - timedelta(minutes=2)
    activacion.ultimo_reenvio_en = None
    db.commit()
    db.rollback()
    transporte.mensajes.clear()

    barrera = Barrier(2)
    monkeypatch.setattr(
        "app.api.rutas.operadores.reenviar_invitacion_operador",
        envolver_con_barrera(reenviar_invitacion_operador_servicio, barrera),
    )
    monkeypatch.setattr(
        "app.api.rutas.activaciones_operador.canjear_enlace_operador",
        envolver_con_barrera(canjear_enlace_operador, barrera),
    )

    def reenviar() -> int:
        respuesta = solicitar_con_cookies(
            client,
            "POST",
            f"{RUTA_CREAR_OPERADOR}/{operador_id}/reenviar-invitacion",
            cookies={NOMBRE_COOKIE_SESION: token_admin},
        )
        return respuesta.status_code

    def canjear() -> tuple[int, str | None]:
        respuesta = intercambiar_enlace(client, token_anterior)
        desafio = (
            valor_cookie(respuesta, NOMBRE_COOKIE_DESAFIO)
            if respuesta.status_code == 204
            else None
        )
        return respuesta.status_code, desafio

    with ThreadPoolExecutor(max_workers=2) as executor:
        futuro_reenvio = executor.submit(reenviar)
        futuro_canje = executor.submit(canjear)
        estado_reenvio = futuro_reenvio.result(timeout=30)
        estado_canje, desafio_anterior = futuro_canje.result(timeout=30)

    monkeypatch.setattr(
        "app.api.rutas.activaciones_operador.canjear_enlace_operador",
        canjear_enlace_operador,
    )

    if estado_reenvio != 200 or estado_canje not in (204, 404):
        pytest.fail(
            "El reenvio y el canje concurrentes devolvieron estados inesperados."
        )
    token_nuevo = token_del_ultimo_mensaje(transporte)
    db.rollback()
    db.expire_all()
    activaciones = db.scalars(
        select(ActivacionCuenta)
        .where(ActivacionCuenta.usuario_id == operador_id)
        .order_by(ActivacionCuenta.id)
    ).all()
    actual = activaciones[-1] if activaciones else None
    if (
        len(activaciones) != 2
        or activaciones[0].consumido_en is None
        or activaciones[0].desafio_hash is not None
        or actual is None
        or actual.consumido_en is not None
        or actual.token_hash != hash_token_activacion(token_nuevo)
    ):
        estado_final = {
            "filas": len(activaciones),
            "anterior_consumida": bool(activaciones and activaciones[0].consumido_en),
            "desafio_anterior_borrado": bool(
                activaciones and activaciones[0].desafio_hash is None
            ),
            "nueva_consumida": bool(actual and actual.consumido_en),
            "token_nuevo_coincide": bool(
                actual and actual.token_hash == hash_token_activacion(token_nuevo)
            ),
            "http_reenvio": estado_reenvio,
            "http_canje": estado_canje,
        }
        pytest.fail(f"Invariantes de carrera no cumplidas: {estado_final}.")
    if desafio_anterior is not None:
        estado_desafio = solicitar_con_cookies(
            client,
            "GET",
            f"{RUTA_ACTIVACION}/desafio",
            cookies={NOMBRE_COOKIE_DESAFIO: desafio_anterior},
        )
        if estado_desafio.json() != {"valido": False}:
            pytest.fail("El desafio emitido durante la carrera siguio vigente.")
        completar_anterior = solicitar_con_cookies(
            client,
            "POST",
            f"{RUTA_ACTIVACION}/completar",
            json={"nueva_contrasena": CONTRASENA_NUEVA},
            cookies={NOMBRE_COOKIE_DESAFIO: desafio_anterior},
        )
        exigir_estado_http(
            completar_anterior,
            404,
            "Completar con el desafio supersedido durante la carrera",
        )
    if intercambiar_enlace(client, token_anterior).status_code != 404:
        pytest.fail("El enlace anterior siguio utilizable despues del reenvio.")
    exigir_estado_http(
        intercambiar_enlace(client, token_nuevo),
        204,
        "Canjear el enlace nuevo despues de la carrera",
    )


def test_reenvio_concurrente_con_completar_no_reactiva_un_desafio_supersedido(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operador, token_anterior, transporte, _settings, token_admin = crear_invitacion(
        db,
        client,
        monkeypatch,
    )
    operador_id = operador.id
    canje = intercambiar_enlace(client, token_anterior)
    exigir_estado_http(canje, 204, "Canje previo a la carrera de reenvio y activacion")
    desafio_anterior = valor_cookie(canje, NOMBRE_COOKIE_DESAFIO)
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador_id)
    )
    if activacion is None:
        pytest.fail("No se encontro la invitacion sintetica inicial.")
    activacion.creado_en = datetime.now(UTC) - timedelta(minutes=2)
    activacion.ultimo_reenvio_en = None
    db.commit()
    db.rollback()
    transporte.mensajes.clear()

    barrera = Barrier(2)
    monkeypatch.setattr(
        "app.api.rutas.operadores.reenviar_invitacion_operador",
        envolver_con_barrera(reenviar_invitacion_operador_servicio, barrera),
    )
    monkeypatch.setattr(
        "app.api.rutas.activaciones_operador.completar_activacion_operador",
        envolver_con_barrera(completar_activacion_operador, barrera),
    )

    def reenviar() -> int:
        respuesta = solicitar_con_cookies(
            client,
            "POST",
            f"{RUTA_CREAR_OPERADOR}/{operador_id}/reenviar-invitacion",
            cookies={NOMBRE_COOKIE_SESION: token_admin},
        )
        return respuesta.status_code

    def completar() -> int:
        respuesta = solicitar_con_cookies(
            client,
            "POST",
            f"{RUTA_ACTIVACION}/completar",
            json={"nueva_contrasena": CONTRASENA_OPERADOR},
            cookies={NOMBRE_COOKIE_DESAFIO: desafio_anterior},
        )
        return respuesta.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futuro_reenvio = executor.submit(reenviar)
        futuro_completar = executor.submit(completar)
        estado_reenvio = futuro_reenvio.result(timeout=30)
        estado_completar = futuro_completar.result(timeout=30)

    if estado_reenvio not in (200, 409) or estado_completar not in (200, 404):
        pytest.fail(
            "El reenvio y la activacion concurrentes devolvieron estados inesperados."
        )
    db.rollback()
    db.expire_all()
    usuario = db.get(Usuario, operador_id)
    activaciones = db.scalars(
        select(ActivacionCuenta)
        .where(ActivacionCuenta.usuario_id == operador_id)
        .order_by(ActivacionCuenta.id)
    ).all()
    if usuario is None or not activaciones:
        pytest.fail("La carrera dejo incompleta la identidad o invitacion.")
    if usuario.correo_verificado:
        if (
            estado_completar != 200
            or len(activaciones) != 1
            or usuario.contrasena_hash is None
            or activaciones[-1].consumido_en is None
            or any(fila.desafio_hash is not None for fila in activaciones)
        ):
            estado_final = {
                "reenvio": estado_reenvio,
                "completar": estado_completar,
                "filas": len(activaciones),
                "contrasena_presente": usuario.contrasena_hash is not None,
                "filas_consumidas": [
                    fila.consumido_en is not None for fila in activaciones
                ],
                "hashes_desafio_presentes": [
                    fila.desafio_hash is not None for fila in activaciones
                ],
            }
            pytest.fail(f"Invariantes de activacion no cumplidas: {estado_final}.")
        if transporte.mensajes:
            token_candidato = token_del_ultimo_mensaje(transporte)
            if intercambiar_enlace(client, token_candidato).status_code != 404:
                pytest.fail("Un correo de reenvio tardio produjo un enlace utilizable.")
    else:
        token_nuevo = token_del_ultimo_mensaje(transporte)
        if (
            estado_completar != 404
            or estado_reenvio != 200
            or usuario.contrasena_hash is not None
            or len(activaciones) != 2
            or activaciones[0].consumido_en is None
            or activaciones[0].desafio_hash is not None
            or activaciones[-1].token_hash != hash_token_activacion(token_nuevo)
            or activaciones[-1].consumido_en is not None
        ):
            pytest.fail("El reenvio ganador no sustituyo la invitacion anterior.")
        exigir_estado_http(
            intercambiar_enlace(client, token_nuevo),
            204,
            "Canjear la nueva invitacion tras la carrera",
        )

    estado_anterior = solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: desafio_anterior},
    )
    if estado_anterior.json() != {"valido": False}:
        pytest.fail("El desafio anterior permanecio valido al terminar la carrera.")
    if db.scalar(select(Sesion.id).where(Sesion.usuario_id == operador_id)) is not None:
        pytest.fail("La carrera de activacion creo una sesion autenticada.")


def test_desactivar_concurrente_con_completar_deja_cuenta_bloqueada_y_sin_sesion(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operador, token_enlace, _transporte, _settings, token_admin = crear_invitacion(
        db,
        client,
        monkeypatch,
    )
    operador_id = operador.id
    canje = intercambiar_enlace(client, token_enlace)
    exigir_estado_http(canje, 204, "Canje previo a la carrera de desactivacion")
    desafio = valor_cookie(canje, NOMBRE_COOKIE_DESAFIO)

    barrera = Barrier(2)
    monkeypatch.setattr(
        "app.api.rutas.operadores.desactivar_operador",
        envolver_con_barrera(desactivar_operador_servicio, barrera),
    )
    monkeypatch.setattr(
        "app.api.rutas.activaciones_operador.completar_activacion_operador",
        envolver_con_barrera(completar_activacion_operador, barrera),
    )

    def desactivar() -> int:
        respuesta = solicitar_con_cookies(
            client,
            "POST",
            f"{RUTA_CREAR_OPERADOR}/{operador_id}/desactivar",
            cookies={NOMBRE_COOKIE_SESION: token_admin},
        )
        return respuesta.status_code

    def completar() -> int:
        respuesta = solicitar_con_cookies(
            client,
            "POST",
            f"{RUTA_ACTIVACION}/completar",
            json={"nueva_contrasena": CONTRASENA_OPERADOR},
            cookies={NOMBRE_COOKIE_DESAFIO: desafio},
        )
        return respuesta.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futuro_desactivar = executor.submit(desactivar)
        futuro_completar = executor.submit(completar)
        estado_desactivar = futuro_desactivar.result(timeout=30)
        estado_completar = futuro_completar.result(timeout=30)

    if estado_desactivar != 200 or estado_completar not in (200, 404):
        pytest.fail("La carrera de desactivacion devolvio estados inesperados.")
    db.rollback()
    db.expire_all()
    usuario = db.get(Usuario, operador_id)
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador_id)
    )
    if usuario is None or activacion is None or usuario.esta_activo:
        pytest.fail("La cuenta no termino desactivada despues de la carrera.")
    if usuario.correo_verificado:
        if (
            estado_completar != 200
            or usuario.contrasena_hash is None
            or activacion.consumido_en is None
        ):
            pytest.fail(
                "La activacion ganadora dejo un estado de credenciales inconsistente."
            )
    elif (
        estado_completar != 404
        or usuario.contrasena_hash is not None
        or activacion.consumido_en is None
    ):
        pytest.fail("La desactivacion ganadora no invalido la invitacion pendiente.")
    if activacion.desafio_hash is not None:
        pytest.fail("La cuenta desactivada conserva un desafio utilizable.")
    if db.scalar(select(Sesion.id).where(Sesion.usuario_id == operador_id)) is not None:
        pytest.fail("La cuenta desactivada conserva una sesion utilizable.")
    estado_desafio = solicitar_con_cookies(
        client,
        "GET",
        f"{RUTA_ACTIVACION}/desafio",
        cookies={NOMBRE_COOKIE_DESAFIO: desafio},
    )
    if estado_desafio.json() != {"valido": False}:
        pytest.fail("La cookie de desafio se reactivo despues de desactivar la cuenta.")
    login = client.post(
        "/api/autenticacion/login",
        json={"correo": usuario.correo, "contrasena": CONTRASENA_OPERADOR},
    )
    exigir_estado_http(login, 401, "Login de OPERADOR desactivado")
    if "set-cookie" in login.headers:
        pytest.fail("El login de una cuenta desactivada creo una cookie de sesion.")
