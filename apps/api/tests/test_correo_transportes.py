from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from uuid import uuid4

import pytest
from fastapi import Response
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.api.rutas.activaciones import reenviar_activacion_endpoint
from app.core.config import Settings
from app.correo.mensajes import (
    DatosActivacionCorreo,
    construir_datos_activacion,
)
from app.correo.smtp import (
    ConfiguracionSMTPInvalidaError,
    SMTPTransport,
    cargar_configuracion_smtp,
)
from app.correo.transportes import crear_transporte_correo
from app.esquemas.activaciones import SolicitudReenvioActivacion
from app.models import Usuario
from app.seguridad.contrasenas import verificar_contrasena
from app.servicios.activaciones import (
    ActivacionNoDisponible,
    activar_cuenta_manual,
    activar_cuenta_temporal,
    crear_activacion,
    reenviar_activacion,
)
from app.servicios.usuarios import crear_admin


def correo_de_prueba() -> str:
    return f"correo-activacion-{uuid4().hex}@example.com"


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
        "smtp_host": "mailpit",
        "smtp_port": "1025",
        "smtp_username": "",
        "smtp_password": SecretStr(""),
        "smtp_from_email": "no-reply@example.test",
        "smtp_from_name": "Smart Parking",
        "smtp_security": "none",
        "smtp_timeout_seconds": "10",
        "app_public_url": "http://localhost:3000",
    }
    valores.update(overrides)
    return Settings(**valores)


def settings_smtp_de_prueba(**overrides: Any) -> Settings:
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
        "smtp_password": SecretStr("smtp-secret-not-for-output"),
        "smtp_from_email": "no-reply@example.com",
        "smtp_from_name": "Smart Parking",
        "smtp_security": "ssl",
        "smtp_timeout_seconds": "10",
        "app_public_url": "http://localhost:3000",
    }
    valores.update(overrides)
    return Settings(**valores)


def crear_usuario_manual(db: Session) -> Usuario:
    resultado = crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo_de_prueba(),
        contrasena="Contrasena manual activacion 123",
        confirmacion_contrasena="Contrasena manual activacion 123",
    )
    return resultado.usuario


def crear_usuario_temporal(db: Session) -> tuple[Usuario, str]:
    resultado = crear_admin(
        db,
        nombre="Grace",
        apellido_paterno="Hopper",
        apellido_materno="Murray",
        correo=correo_de_prueba(),
        usar_contrasena_temporal=True,
    )
    assert resultado.contrasena_temporal is not None
    return resultado.usuario, resultado.contrasena_temporal


class TransporteEnMemoria:
    """Conserva datos de entrega solo dentro de la prueba actual."""

    def __init__(self) -> None:
        self.mensajes: list[DatosActivacionCorreo | EmailMessage] = []

    def enviar(self, datos: DatosActivacionCorreo | EmailMessage) -> None:
        self.mensajes.append(datos)


def test_fabrica_solo_crea_transporte_smtp() -> None:
    settings = settings_de_prueba()

    assert isinstance(crear_transporte_correo(settings), SMTPTransport)
    assert cargar_configuracion_smtp(settings).from_email == "no-reply@example.test"


def test_configuracion_smtp_development_valida() -> None:
    settings = settings_smtp_de_prueba()

    transporte = crear_transporte_correo(settings)

    assert isinstance(transporte, SMTPTransport)
    assert cargar_configuracion_smtp(settings).host == "smtp.test.invalid"


def test_configuracion_smtp_development_sin_requeridos_falla_al_enviar() -> None:
    settings = settings_smtp_de_prueba(
        smtp_host=None,
        smtp_username=None,
        smtp_password=None,
        smtp_from_email=None,
    )
    mensaje = EmailMessage()
    mensaje["To"] = "admin@example.com"
    mensaje.set_content("prueba")

    with pytest.raises(ConfiguracionSMTPInvalidaError):
        SMTPTransport(settings).enviar(mensaje)


def test_configuracion_smtp_production_valida() -> None:
    settings = settings_smtp_de_prueba(app_environment="production")

    transporte = crear_transporte_correo(settings)

    assert isinstance(transporte, SMTPTransport)
    assert cargar_configuracion_smtp(settings).security == "ssl"


def test_activacion_manual_real_usa_transporte_en_memoria(
    db: Session,
) -> None:
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion(db, usuario.id)
    settings = settings_de_prueba()
    datos = construir_datos_activacion(
        usuario,
        resultado,
        None,
        settings=settings,
    )

    transporte = TransporteEnMemoria()
    transporte.enviar(datos)

    assert transporte.mensajes == [datos]
    activar_cuenta_manual(db, token=resultado.token, codigo=resultado.codigo)
    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    assert usuario_persistido is not None
    assert usuario_persistido.correo_verificado is True


def test_activacion_temporal_real_usa_transporte_en_memoria(
    db: Session,
) -> None:
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
    settings = settings_de_prueba()
    datos = construir_datos_activacion(
        resultado_usuario.usuario,
        resultado,
        resultado_usuario.contrasena_temporal,
        settings=settings,
    )
    nueva_contrasena = "Contrasena definitiva activacion 123"

    transporte = TransporteEnMemoria()
    transporte.enviar(datos)
    assert transporte.mensajes == [datos]
    activar_cuenta_temporal(
        db,
        token=resultado.token,
        codigo=resultado.codigo,
        contrasena_temporal=resultado_usuario.contrasena_temporal,
        nueva_contrasena=nueva_contrasena,
        confirmar_contrasena=nueva_contrasena,
    )
    db.rollback()
    usuario_persistido = db.get(Usuario, resultado_usuario.usuario.id)
    assert usuario_persistido is not None
    assert usuario_persistido.correo_verificado is True
    assert usuario_persistido.debe_cambiar_contrasena is False
    assert usuario_persistido.contrasena_hash is not None
    assert verificar_contrasena(
        nueva_contrasena,
        usuario_persistido.contrasena_hash,
    )


def test_endpoint_publico_no_emite_nuevas_invitaciones_legacy(
    db: Session,
    capsys,
) -> None:
    usuario = crear_usuario_manual(db)

    respuesta = reenviar_activacion_endpoint(
        SolicitudReenvioActivacion(correo=usuario.correo),
        Response(),
        db,
    )

    assert respuesta.estado
    salida = capsys.readouterr().out
    assert salida == ""
    assert usuario.correo not in salida


def test_endpoint_publico_no_muestra_credenciales_temporales(
    db: Session,
    capsys,
) -> None:
    usuario, _password_anterior = crear_usuario_temporal(db)

    respuesta = reenviar_activacion_endpoint(
        SolicitudReenvioActivacion(correo=usuario.correo),
        Response(),
        db,
    )

    assert respuesta.estado
    salida = capsys.readouterr().out
    assert salida == ""
    assert usuario.correo not in salida


def test_reenvio_temporal_invalida_anterior_y_activa_nuevo(
    db: Session,
) -> None:
    usuario, password_anterior = crear_usuario_temporal(db)
    settings = settings_de_prueba()
    inicio = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    primera = crear_activacion(db, usuario.id, ahora=inicio)
    primera.activacion.creado_en = inicio
    db.commit()
    db.rollback()

    segunda = reenviar_activacion(
        db,
        usuario.correo,
        cooldown_segundos=settings.activacion_reenvio_cooldown_segundos,
        ahora=inicio + timedelta(seconds=61),
    )
    assert segunda is not None
    assert segunda.contrasena_temporal is not None
    datos = construir_datos_activacion(
        segunda.usuario,
        segunda,
        segunda.contrasena_temporal,
        settings=settings,
        es_reenvio=True,
    )
    transporte = TransporteEnMemoria()
    transporte.enviar(datos)
    assert transporte.mensajes == [datos]

    with pytest.raises(ActivacionNoDisponible):
        activar_cuenta_temporal(
            db,
            token=primera.token,
            codigo=primera.codigo,
            contrasena_temporal=password_anterior,
            nueva_contrasena="Contrasena definitiva invalida 123",
            confirmar_contrasena="Contrasena definitiva invalida 123",
        )

    db.rollback()
    nueva_contrasena = "Contrasena definitiva reenvio 123"
    activar_cuenta_temporal(
        db,
        token=segunda.token,
        codigo=segunda.codigo,
        contrasena_temporal=segunda.contrasena_temporal,
        nueva_contrasena=nueva_contrasena,
        confirmar_contrasena=nueva_contrasena,
        ahora=inicio + timedelta(seconds=61),
    )
    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    assert usuario_persistido is not None
    assert usuario_persistido.correo_verificado is True
