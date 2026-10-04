from __future__ import annotations

import os
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.cli import crear_admin as cli
from app.core.config import Settings, get_settings
from app.correo.mensajes import (
    ASUNTO_ACTIVACION,
    DatosActivacionCorreo,
    construir_mensaje_activacion,
    construir_url_activacion,
)
from app.correo.smtp import (
    ConfiguracionSMTPInvalidaError,
    ErrorEnvioCorreo,
    SMTPTransport,
    cargar_configuracion_smtp,
)
from app.models import ActivacionCuenta, Sesion, Usuario
from app.seguridad.activaciones import (
    generar_codigo_verificacion,
    hash_token_activacion,
)
from app.seguridad.contrasenas import verificar_contrasena
from app.servicios.activaciones import (
    ActivacionPendienteExistenteError,
    ErrorCreacionActivacion,
    crear_activacion,
)
from app.servicios.usuarios import crear_admin


class FakeTransport:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.mensajes: list[DatosActivacionCorreo | EmailMessage] = []
        self.error = error

    def enviar(self, datos: DatosActivacionCorreo | EmailMessage) -> None:
        if self.error is not None:
            raise self.error
        self.mensajes.append(datos)


def correo_de_prueba() -> str:
    return f"sp004-test-{uuid4().hex}@example.com"


def settings_de_prueba(**overrides: object) -> Settings:
    valores: dict[str, Any] = {
        "database_host": "localhost",
        "database_port": 5432,
        "database_name": "unused",
        "database_user": "unused",
        "database_password": "test-db-password",
        "activation_token_ttl_hours": 24,
        "activation_challenge_ttl_minutes": 15,
        "correo_transporte": "smtp",
        "smtp_host": "smtp.test.invalid",
        "smtp_port": "465",
        "smtp_username": "smtp-user",
        "smtp_password": SecretStr("smtp-secret-not-for-output"),
        "smtp_from_email": "no-reply@example.com",
        "smtp_from_name": "Smart Parking",
        "smtp_security": "ssl",
        "smtp_timeout_seconds": "10",
        "app_public_url": "https://parking.example/base",
    }
    valores.update(overrides)
    return Settings(**valores)


def cuerpo(mensaje: EmailMessage, parte: str) -> str:
    cuerpo_mensaje = mensaje.get_body(preferencelist=(parte,))
    assert cuerpo_mensaje is not None
    return cuerpo_mensaje.get_content()


def crear_usuario(db: Session, *, correo: str | None = None) -> Usuario:
    resultado = crear_admin(
        db,
        nombre="Ada <script>",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo or correo_de_prueba(),
        contrasena="Contrasena de prueba 123",
        confirmacion_contrasena="Contrasena de prueba 123",
    )
    return resultado.usuario


def test_crear_activacion_persiste_hashes_y_expiracion(db: Session) -> None:
    ahora = datetime(2026, 9, 26, 20, 0, tzinfo=UTC)
    usuario = crear_usuario(db)

    resultado = crear_activacion(db, usuario.id, ahora=ahora)
    persistida = db.get(ActivacionCuenta, resultado.activacion.id)

    assert persistida is not None
    assert persistida.usuario_id == usuario.id
    assert persistida.consumido_en is None
    assert persistida.expira_en.tzinfo is not None
    assert timedelta(minutes=14, seconds=59) < persistida.expira_en - ahora
    assert persistida.expira_en - ahora <= timedelta(minutes=15)
    assert persistida.token_hash == hash_token_activacion(resultado.token)
    assert persistida.token_hash != resultado.token
    assert persistida.codigo_hash is not None
    assert persistida.codigo_hash != resultado.codigo
    assert persistida.codigo_hash.startswith("$argon2id$")
    assert verificar_contrasena(resultado.codigo, persistida.codigo_hash)
    assert len(resultado.codigo) == 6
    assert resultado.codigo.isdecimal()
    assert repr(resultado.token) not in repr(resultado.activacion)
    assert "token=" not in repr(resultado)
    assert "codigo=" not in repr(resultado)


def test_dos_activaciones_generan_tokens_distintos_y_no_hay_duplicado_pendiente(
    db: Session,
) -> None:
    usuario = crear_usuario(db)
    usuario_id = usuario.id
    primera = crear_activacion(db, usuario.id)
    primera_id = primera.activacion.id

    with pytest.raises(ActivacionPendienteExistenteError):
        crear_activacion(db, usuario_id)

    db.query(ActivacionCuenta).filter_by(id=primera_id).update(
        {ActivacionCuenta.expira_en: datetime.now(UTC) - timedelta(seconds=1)}
    )
    db.commit()
    segunda = crear_activacion(db, usuario_id)
    assert primera.token != segunda.token
    assert primera.codigo != segunda.codigo


def test_modelo_no_declara_secretos_en_crudo() -> None:
    columnas = {columna.name for columna in ActivacionCuenta.__table__.columns}
    assert {
        "token",
        "codigo",
        "contrasena_temporal",
        "raw_activation_token",
        "raw_verification_code",
    }.isdisjoint(columnas)


def test_codigo_preserva_ceros_iniciales() -> None:
    with patch("app.seguridad.activaciones.secrets.randbelow", return_value=7):
        assert generar_codigo_verificacion() == "000007"


def test_mensaje_manual_tiene_texto_html_y_no_password(db: Session) -> None:
    settings = settings_de_prueba()
    usuario = crear_usuario(db)
    resultado = crear_activacion(db, usuario.id)
    mensaje = construir_mensaje_activacion(
        usuario,
        resultado,
        None,
        settings=settings,
    )
    texto = cuerpo(mensaje, "plain")
    html = cuerpo(mensaje, "html")

    assert mensaje["Subject"] == ASUNTO_ACTIVACION
    assert mensaje["To"] == usuario.correo
    assert mensaje.is_multipart()
    assert "/activar?token=" in texto
    assert "&modo=" not in texto
    assert resultado.token in texto
    assert resultado.codigo in texto
    assert "15 minutos" in texto
    assert "Contrasena temporal:" not in texto
    assert "Ada &lt;script&gt;" in html
    assert "<script>" not in html
    assert resultado.token in html
    assert resultado.codigo in html
    assert resultado.token not in mensaje["Subject"]
    assert resultado.codigo not in mensaje["Subject"]


def test_mensaje_automatico_incluye_password_y_explica_reemplazo(db: Session) -> None:
    settings = settings_de_prueba()
    resultado_usuario = crear_admin(
        db,
        nombre="Grace",
        apellido_paterno="Hopper",
        apellido_materno="Murray",
        correo=correo_de_prueba(),
        usar_contrasena_temporal=True,
    )
    assert resultado_usuario.contrasena_temporal is not None
    resultado = crear_activacion(db, resultado_usuario.usuario.id)
    mensaje = construir_mensaje_activacion(
        resultado_usuario.usuario,
        resultado,
        resultado_usuario.contrasena_temporal,
        settings=settings,
    )
    texto = cuerpo(mensaje, "plain")
    html = cuerpo(mensaje, "html")

    assert resultado_usuario.contrasena_temporal in texto
    assert "/activar?token=" in texto
    assert "&modo=" not in texto
    assert "reemplazar esta contrasena" in texto
    assert resultado_usuario.contrasena_temporal in html
    assert "reemplazar esta contrasena" in html


def test_url_activacion_codifica_token_y_rechaza_base_insegura() -> None:
    token = "a/b+c?d=&e"
    url = construir_url_activacion(
        token,
        "https://example.com/app/",
    )
    assert url == "https://example.com/app/activar?token=a%2Fb%2Bc%3Fd%3D%26e"

    with pytest.raises(ConfiguracionSMTPInvalidaError):
        construir_url_activacion(token, "example.com")


@pytest.mark.parametrize(
    "security, constructor", [("ssl", "SMTP_SSL"), ("starttls", "SMTP")]
)
def test_smtp_usa_transporte_seguro_y_autentica(
    security: str,
    constructor: str,
) -> None:
    settings = settings_de_prueba(smtp_security=security)
    mensaje = EmailMessage()
    mensaje["From"] = "no-reply@example.com"
    mensaje["To"] = "destino@example.com"
    mensaje["Subject"] = "Prueba"
    mensaje.set_content("prueba")
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    smtp.send_message.return_value = {}

    with patch(
        f"app.correo.smtp.smtplib.{constructor}",
        return_value=smtp,
    ) as smtp_constructor:
        SMTPTransport(settings).enviar(mensaje)

    smtp_constructor.assert_called_once()
    argumentos = smtp_constructor.call_args.kwargs
    assert argumentos["timeout"] == 10.0
    smtp.login.assert_called_once_with("smtp-user", "smtp-secret-not-for-output")
    smtp.send_message.assert_called_once_with(mensaje)
    if security == "starttls":
        smtp.starttls.assert_called_once()
        assert smtp.ehlo.call_count == 2
    else:
        smtp.starttls.assert_not_called()


def test_smtp_none_no_usa_tls_ni_login() -> None:
    settings = settings_de_prueba(
        app_environment="development",
        smtp_security="none",
        smtp_username="",
        smtp_password=SecretStr(""),
    )
    mensaje = EmailMessage()
    mensaje["From"] = "no-reply@example.com"
    mensaje["To"] = "destino@example.com"
    mensaje["Subject"] = "Prueba local"
    mensaje.set_content("prueba")
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    smtp.send_message.return_value = {}

    with patch("app.correo.smtp.smtplib.SMTP", return_value=smtp) as constructor:
        with patch("app.correo.smtp.smtplib.SMTP_SSL") as constructor_ssl:
            SMTPTransport(settings).enviar(mensaje)

    constructor.assert_called_once()
    constructor_ssl.assert_not_called()
    smtp.starttls.assert_not_called()
    smtp.login.assert_not_called()
    smtp.send_message.assert_called_once_with(mensaje)


@pytest.mark.parametrize(
    "overrides",
    [
        {"smtp_host": None},
        {"smtp_username": None},
        {"smtp_password": None},
        {"smtp_port": "no-es-un-puerto"},
        {"smtp_security": "plaintext"},
        {"smtp_timeout_seconds": "0"},
    ],
)
def test_smtp_rechaza_configuracion_invalida_sin_conectarse(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ConfiguracionSMTPInvalidaError):
        cargar_configuracion_smtp(settings_de_prueba(**overrides))


def test_smtp_fallo_se_traduce_a_error_sin_exponer_password() -> None:
    settings = settings_de_prueba()
    mensaje = EmailMessage()
    mensaje["From"] = "no-reply@example.com"
    mensaje["To"] = "destino@example.com"
    mensaje.set_content("prueba")
    with patch(
        "app.correo.smtp.smtplib.SMTP_SSL",
        side_effect=TimeoutError("smtp-secret-not-for-output"),
    ):
        with pytest.raises(ErrorEnvioCorreo) as error:
            SMTPTransport(settings).enviar(mensaje)

    assert str(error.value) == "No fue posible enviar el correo de activacion."
    assert "smtp-secret-not-for-output" not in str(error.value)


@pytest.mark.parametrize(
    "smtp_error",
    [
        smtplib.SMTPAuthenticationError(535, "rejected"),
        smtplib.SMTPServerDisconnected("disconnected"),
        smtplib.SMTPException("protocol failure"),
        ssl.SSLError("tls failure"),
        ConnectionRefusedError("refused"),
    ],
)
def test_smtp_errores_de_red_y_protocolo_son_seguros(smtp_error: Exception) -> None:
    settings = settings_de_prueba()
    mensaje = EmailMessage()
    mensaje["From"] = "no-reply@example.com"
    mensaje["To"] = "destino@example.com"
    mensaje.set_content("prueba")
    with patch(
        "app.correo.smtp.smtplib.SMTP_SSL",
        side_effect=smtp_error,
    ):
        with pytest.raises(ErrorEnvioCorreo):
            SMTPTransport(settings).enviar(mensaje)


def test_flujo_automatico_con_fallo_smtp_no_imprime_password(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = settings_de_prueba()
    transporte = FakeTransport(error=ErrorEnvioCorreo())
    correo = correo_de_prueba()
    respuestas = iter(["Grace", "Hopper", "Murray", correo])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(respuestas))

    assert (
        cli.main(
            db=db,
            transporte=transporte,
            settings=settings,
        )
        == 1
    )
    salida = capsys.readouterr()
    assert "Contrasena temporal:" not in salida.out + salida.err
    usuario = db.scalar(select(Usuario).where(Usuario.correo == correo))
    assert usuario is None
    assert db.scalar(select(func.count()).select_from(ActivacionCuenta)) == 0


def test_cli_exitoso_no_imprime_password_ni_credenciales(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = settings_de_prueba()
    transporte = FakeTransport()
    correo = correo_de_prueba()
    respuestas = iter(["Ada", "Lovelace", "Byron", correo])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(respuestas))

    assert (
        cli.main(
            db=db,
            transporte=transporte,
            settings=settings,
        )
        == 0
    )
    salida = capsys.readouterr()
    assert "ADMIN creado. Correo de activacion enviado." in salida.out
    assert "Contrasena temporal:" not in salida.out
    assert "Codigo de verificacion" not in salida.out
    assert len(transporte.mensajes) == 1
    mensaje = transporte.mensajes[0]
    assert isinstance(mensaje, EmailMessage)
    assert mensaje["To"] == correo
    parte_plana = mensaje.get_body(preferencelist=("plain",))
    assert parte_plana is not None
    cuerpo_plano = str(parte_plana.get_content())
    assert "/activar-cuenta?token=" in cuerpo_plano
    assert "/activar?" not in cuerpo_plano
    assert "Código:" not in cuerpo_plano
    assert "Contraseña temporal" not in cuerpo_plano
    usuario = db.scalar(select(Usuario).where(Usuario.correo == correo))
    assert usuario is not None
    assert usuario.contrasena_hash is None
    assert usuario.correo_verificado is False
    assert (
        db.scalar(
            select(func.count())
            .select_from(ActivacionCuenta)
            .join(Usuario)
            .where(Usuario.correo == correo)
        )
        == 1
    )
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0


def test_cli_fallo_smtp_revierte_creacion_y_no_emite_credenciales(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = settings_de_prueba()
    transporte = FakeTransport(error=ErrorEnvioCorreo())
    correo = correo_de_prueba()
    respuestas = iter(["Ada", "Lovelace", "Byron", correo])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(respuestas))

    assert (
        cli.main(
            db=db,
            transporte=transporte,
            settings=settings,
        )
        == 1
    )
    salida = capsys.readouterr()
    assert "No fue posible completar la entrega de la invitacion ADMIN." in salida.err
    assert "contraseña" not in salida.out.casefold()
    usuario = db.scalar(select(Usuario).where(Usuario.correo == correo))
    assert usuario is None
    assert db.scalar(select(func.count()).select_from(ActivacionCuenta)) == 0
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0


def test_fallo_de_base_de_datos_hace_rollback_de_activacion(db: Session) -> None:
    usuario = crear_usuario(db)
    usuario_id = usuario.id
    cantidad_antes = db.scalar(select(func.count()).select_from(ActivacionCuenta))
    db.rollback()
    with patch.object(
        db, "flush", side_effect=IntegrityError("insert", {}, RuntimeError())
    ):
        with pytest.raises(ErrorCreacionActivacion):
            crear_activacion(db, usuario_id)
    assert (
        db.scalar(select(func.count()).select_from(ActivacionCuenta)) == cantidad_antes
    )


def test_smtp_live_es_opcional() -> None:
    required = (
        "SMTP_HOST",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM_EMAIL",
        "SMTP_LIVE_TEST_TO",
    )
    if not all(os.environ.get(nombre) for nombre in required):
        pytest.skip("SMTP_LIVE_TEST_TO y credenciales SMTP no estan configurados")

    settings = get_settings().model_copy(
        update={"database_name": os.environ["DATABASE_NAME"]}
    )
    mensaje = EmailMessage()
    mensaje["Subject"] = "Prueba SMTP de Smart Parking"
    mensaje["From"] = settings.smtp_from_email or ""
    mensaje["To"] = os.environ["SMTP_LIVE_TEST_TO"]
    mensaje.set_content("Prueba SMTP explicita de Smart Parking.")
    SMTPTransport(settings).enviar(mensaje)
