"""Regresiones SP-026 para entrega segura de credenciales OPERADOR."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from unittest.mock import MagicMock, patch
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

from app.core.config import Settings
from app.core.database import get_db
from app.correo.errores import ErrorCorreo, ErrorEnvioCorreo
from app.correo.mensajes import (
    DatosActivacionCorreo,
    construir_mensaje_invitacion_operador,
)
from app.correo.smtp import SMTPTransport
from app.esquemas.operadores import RespuestaCrearOperador
from app.models import ActivacionCuenta, RolUsuario, Sesion, Usuario
from app.seguridad.activaciones import hash_token_activacion
from app.seguridad.contrasenas import crear_hash_contrasena
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.usuarios import crear_admin, crear_operador
from main import app

RUTA_CREAR_OPERADOR = "/api/admin/operadores"
NOMBRE_COOKIE = "smart_parking_session"
CONTRASENA_ADMIN = "Contrasena segura SP026 123"


class FakeTransport:
    """Captura MIME en memoria o simula un error tipado de entrega."""

    def __init__(self, error: ErrorCorreo | None = None) -> None:
        self.mensajes: list[EmailMessage] = []
        self.error = error

    def enviar(self, datos: DatosActivacionCorreo | EmailMessage) -> None:
        if self.error is not None:
            raise self.error
        if not isinstance(datos, EmailMessage):
            raise ErrorEnvioCorreo
        self.mensajes.append(datos)


def correo_de_prueba() -> str:
    return f"sp026-test-{uuid4().hex}@example.com"


def settings_de_prueba(**overrides: Any) -> Settings:
    valores: dict[str, Any] = {
        "database_host": "localhost",
        "database_port": 5432,
        "database_name": "unused",
        "database_user": "unused",
        "database_password": "test-db-password",
        "activation_token_ttl_hours": 24,
        "activation_challenge_ttl_minutes": 15,
        "app_environment": "development",
        "correo_transporte": "smtp",
        "smtp_host": "smtp.test.invalid",
        "smtp_port": "465",
        "smtp_username": "smtp-user",
        "smtp_password": SecretStr("smtp-secret-no-output"),
        "smtp_from_email": "no-reply@example.com",
        "smtp_from_name": "Smart Parking",
        "smtp_security": "ssl",
        "smtp_timeout_seconds": "10",
    }
    valores.update(overrides)
    return Settings(**valores)


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
    usuario.esta_activo = True
    usuario.correo_verificado = True
    usuario.debe_cambiar_contrasena = False
    db.commit()
    db.rollback()

    token = f"token-sp026-{uuid4().hex}"
    ahora = datetime.now(UTC)
    db.add(
        Sesion(
            usuario_id=usuario.id,
            token_hash=hash_token_sesion(token),
            expira_en=ahora + timedelta(minutes=30),
            revocado_en=None,
            creado_en=ahora,
        )
    )
    db.commit()
    db.rollback()
    return token


def crear_operador_existente(db: Session, correo: str) -> Usuario:
    usuario = Usuario(
        nombre="Grace",
        apellido_paterno="Hopper",
        apellido_materno="Murray",
        correo=correo,
        contrasena_hash=crear_hash_contrasena("Contrasena operador SP026 123"),
        rol=RolUsuario.OPERADOR.value,
        correo_verificado=True,
        esta_activo=True,
        debe_cambiar_contrasena=False,
    )
    db.add(usuario)
    db.commit()
    db.rollback()
    return usuario


def datos_operador(correo: str | None = None) -> dict[str, str]:
    return {
        "nombre": "Grace",
        "apellido_paterno": "Hopper",
        "apellido_materno": "Murray",
        "correo": correo or correo_de_prueba(),
    }


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


@pytest.fixture
def correo_falso(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeTransport, Settings]:
    transporte = FakeTransport()
    settings = settings_de_prueba()
    monkeypatch.setattr("app.api.rutas.operadores.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.api.rutas.operadores.crear_transporte_correo",
        lambda _settings: transporte,
    )
    return transporte, settings


def test_admin_crea_operador_pendiente_y_entrega_un_enlace_de_activacion(
    db: Session,
    client: TestClient,
    correo_falso: tuple[FakeTransport, Settings],
) -> None:
    transporte, _settings = correo_falso
    token = crear_admin_autenticado(db)
    correo = correo_de_prueba()

    respuesta = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=datos_operador(correo),
        cookies={NOMBRE_COOKIE: token},
    )

    assert respuesta.status_code == 201
    assert respuesta.headers["cache-control"] == "no-store"
    assert (
        respuesta.json()
        == RespuestaCrearOperador(estado="operador_creado").model_dump()
    )
    assert len(transporte.mensajes) == 1
    mensaje = transporte.mensajes[0]
    assert mensaje["To"] == correo
    cuerpo = mensaje.get_body(preferencelist=("plain",))
    assert cuerpo is not None
    texto = cuerpo.get_content()
    enlace = next(
        linea for linea in texto.splitlines() if "/activar-cuenta?token=" in linea
    )
    token_invitacion = parse_qs(urlsplit(enlace).query)["token"][0]
    assert "Activar mi cuenta" in texto
    assert "contrasena" not in texto.casefold()
    assert "codigo" not in texto.casefold()

    db.rollback()
    usuario = db.scalar(select(Usuario).where(Usuario.correo == correo))
    assert usuario is not None
    assert usuario.contrasena_hash is None
    assert usuario.correo_verificado is False
    assert "token" not in respuesta.text.casefold()
    assert "contrasena" not in respuesta.text.casefold()
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == usuario.id)
    )
    assert activacion is not None
    assert activacion.codigo_hash is None
    assert activacion.token_hash == hash_token_activacion(token_invitacion)
    assert token_invitacion not in activacion.token_hash
    assert activacion.expira_en - activacion.creado_en == timedelta(hours=24)
    assert (
        db.scalar(
            select(func.count())
            .select_from(Sesion)
            .where(Sesion.usuario_id == usuario.id)
        )
        == 0
    )


def test_solicitud_invalida_no_entrega_ni_crea_operador(
    db: Session,
    client: TestClient,
    correo_falso: tuple[FakeTransport, Settings],
) -> None:
    transporte, _settings = correo_falso
    token = crear_admin_autenticado(db)
    datos = datos_operador()
    datos["correo"] = "correo-invalido"

    respuesta = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=datos,
        cookies={NOMBRE_COOKIE: token},
    )

    assert respuesta.status_code == 422
    assert respuesta.json() == {"detail": "Solicitud invalida"}
    assert transporte.mensajes == []
    assert (
        db.scalar(select(Usuario.id).where(Usuario.rol == RolUsuario.OPERADOR.value))
        is None
    )


def test_correo_duplicado_no_entrega_ni_crea_un_operador_adicional(
    db: Session,
    client: TestClient,
    correo_falso: tuple[FakeTransport, Settings],
) -> None:
    transporte, _settings = correo_falso
    token = crear_admin_autenticado(db)
    correo = correo_de_prueba()
    crear_operador_existente(db, correo)

    respuesta = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=datos_operador(correo),
        cookies={NOMBRE_COOKIE: token},
    )

    assert respuesta.status_code == 409
    assert respuesta.headers["cache-control"] == "no-store"
    assert transporte.mensajes == []
    assert (
        db.scalar(
            select(func.count())
            .select_from(Usuario)
            .where(Usuario.rol == RolUsuario.OPERADOR.value)
        )
        == 1
    )


def test_solicitud_anonima_no_entrega_ni_crea_operador(
    db: Session,
    client: TestClient,
    correo_falso: tuple[FakeTransport, Settings],
) -> None:
    transporte, _settings = correo_falso
    correo = correo_de_prueba()

    respuesta = client.post(RUTA_CREAR_OPERADOR, json=datos_operador(correo))

    assert respuesta.status_code == 401
    assert transporte.mensajes == []
    assert db.scalar(select(Usuario.id).where(Usuario.correo == correo)) is None


def test_sesion_operador_no_entrega_ni_crea_operador(
    db: Session,
    client: TestClient,
    correo_falso: tuple[FakeTransport, Settings],
) -> None:
    transporte, _settings = correo_falso
    operador = crear_operador_existente(db, correo_de_prueba())
    token = f"token-sp026-operador-{uuid4().hex}"
    ahora = datetime.now(UTC)
    db.add(
        Sesion(
            usuario_id=operador.id,
            token_hash=hash_token_sesion(token),
            expira_en=ahora + timedelta(minutes=30),
            revocado_en=None,
            creado_en=ahora,
        )
    )
    db.commit()
    db.rollback()
    correo = correo_de_prueba()

    respuesta = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=datos_operador(correo),
        cookies={NOMBRE_COOKIE: token},
    )

    assert respuesta.status_code == 401
    assert transporte.mensajes == []
    assert db.scalar(select(Usuario.id).where(Usuario.correo == correo)) is None
    assert (
        db.scalar(
            select(func.count())
            .select_from(Usuario)
            .where(Usuario.rol == RolUsuario.OPERADOR.value)
        )
        == 1
    )


def test_fallo_de_entrega_devuelve_503_generico_y_revierte_alta(
    db: Session,
    client: TestClient,
    correo_falso: tuple[FakeTransport, Settings],
) -> None:
    transporte, _settings = correo_falso
    transporte.error = ErrorEnvioCorreo()
    token = crear_admin_autenticado(db)
    correo = correo_de_prueba()

    respuesta = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=datos_operador(correo),
        cookies={NOMBRE_COOKIE: token},
    )

    assert respuesta.status_code == 503
    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.json() == {
        "detail": "Servicio de correo temporalmente no disponible"
    }
    assert correo not in respuesta.text
    assert "activacion" not in respuesta.text
    assert db.scalar(select(Usuario.id).where(Usuario.correo == correo)) is None


def test_configuracion_de_remitente_invalida_devuelve_503_y_revierte_alta(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    correo_falso: tuple[FakeTransport, Settings],
) -> None:
    _transporte, _settings = correo_falso
    settings_invalidos = settings_de_prueba(
        smtp_host=None,
        smtp_username=None,
        smtp_password=None,
    )
    monkeypatch.setattr(
        "app.api.rutas.operadores.get_settings",
        lambda: settings_invalidos,
    )
    monkeypatch.setattr(
        "app.api.rutas.operadores.crear_transporte_correo",
        lambda settings: SMTPTransport(settings),
    )
    token = crear_admin_autenticado(db)
    correo = correo_de_prueba()

    respuesta = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=datos_operador(correo),
        cookies={NOMBRE_COOKIE: token},
    )

    assert respuesta.status_code == 503
    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.json() == {
        "detail": "Servicio de correo temporalmente no disponible"
    }
    assert db.scalar(select(Usuario.id).where(Usuario.correo == correo)) is None


def test_rechazo_smtp_de_destinatario_es_error_de_entrega() -> None:
    settings = settings_de_prueba()
    mensaje = EmailMessage()
    mensaje["From"] = "no-reply@example.com"
    mensaje["To"] = "operador@example.com"
    mensaje["Subject"] = "Credenciales"
    mensaje.set_content("Contrasena: Secreto Operador 123")
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    smtp.send_message.return_value = {
        "operador@example.com": (550, b"rejected recipient")
    }

    with patch("app.correo.smtp.smtplib.SMTP_SSL", return_value=smtp):
        with pytest.raises(ErrorEnvioCorreo) as capturado:
            SMTPTransport(settings).enviar(mensaje)

    assert "operador@example.com" not in str(capturado.value)
    assert "Secreto Operador 123" not in str(capturado.value)


def test_fallo_de_commit_despues_de_aceptacion_smtp_es_no_atomico(
    db: Session,
    correo_falso: tuple[FakeTransport, Settings],
) -> None:
    transporte, settings = correo_falso
    correo = correo_de_prueba()

    def fallar_commit(_sesion: Session) -> None:
        raise SQLAlchemyError("fallo de commit simulado")

    def aceptar_invitacion(usuario: Usuario, token: str) -> None:
        transporte.enviar(
            construir_mensaje_invitacion_operador(
                usuario,
                token,
                settings=settings,
            )
        )

    event.listen(db, "before_commit", fallar_commit)
    try:
        with pytest.raises(SQLAlchemyError, match="fallo de commit simulado"):
            crear_operador(
                db,
                nombre="Grace",
                apellido_paterno="Hopper",
                apellido_materno="Murray",
                correo=correo,
                entregar_invitacion=aceptar_invitacion,
                duracion_token_horas=settings.activation_token_ttl_hours,
            )
    finally:
        event.remove(db, "before_commit", fallar_commit)
        db.rollback()

    assert len(transporte.mensajes) == 1
    assert transporte.mensajes[0]["To"] == correo
    assert db.scalar(select(Usuario.id).where(Usuario.correo == correo)) is None


def test_constructor_escapa_identidad_y_genera_solo_el_enlace_operador() -> None:
    usuario = Usuario(
        nombre="Ada <script>",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo="ada@example.com",
        contrasena_hash="$argon2id$hash-solo-prueba",
        rol=RolUsuario.OPERADOR.value,
    )
    token = "a" * 43
    mensaje = construir_mensaje_invitacion_operador(
        usuario,
        token,
        settings=settings_de_prueba(),
    )
    parte_html = mensaje.get_body(preferencelist=("html",))
    assert parte_html is not None
    html = parte_html.get_content()

    assert "Ada &lt;script&gt;" in html
    assert "Activar mi cuenta" in html
    assert f"/activar-cuenta?token={token}" in html
    assert "contrasena" not in html.casefold()
    assert "codigo" not in html.casefold()
    assert "<script>" not in html
