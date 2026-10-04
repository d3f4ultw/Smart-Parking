from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

import main
from app.core.config import Settings
from app.correo.errores import ConfiguracionSMTPInvalidaError
from app.correo.smtp import cargar_configuracion_smtp

SMTP_SECRET_MARKERS = (
    "SMTP_HOST_SENTINEL_NOT_FOR_OUTPUT_6ca1",
    "SMTP_USERNAME_SENTINEL_NOT_FOR_OUTPUT_84b7",
    "SMTP_PASSWORD_SENTINEL_NOT_FOR_OUTPUT_f311",
    "smtp-from-sentinel-not-for-output-2ad9@example.com",
)


def crear_settings(**overrides: Any) -> Settings:
    valores: dict[str, Any] = {
        "database_host": "localhost",
        "database_port": 5432,
        "database_name": "smart_parking_test",
        "database_user": "smart_parking_test",
        "database_password": SecretStr("test-db-password"),
        "activation_token_ttl_hours": 24,
        "activation_challenge_ttl_minutes": 15,
    }
    valores.update(overrides)
    return Settings.model_validate(valores)


def settings_smtp(**overrides: Any) -> Settings:
    valores: dict[str, Any] = {
        "correo_transporte": "smtp",
        "smtp_host": SMTP_SECRET_MARKERS[0],
        "smtp_port": "465",
        "smtp_username": SMTP_SECRET_MARKERS[1],
        "smtp_password": SecretStr(SMTP_SECRET_MARKERS[2]),
        "smtp_from_email": SMTP_SECRET_MARKERS[3],
        "smtp_from_name": "Smart Parking",
        "smtp_security": "ssl",
        "smtp_timeout_seconds": "10",
    }
    valores.update(overrides)
    return crear_settings(**valores)


def test_database_url_usa_componentes_y_oculta_password_especial() -> None:
    password = 'p$ss:/@"# con espacios\\final'
    settings = crear_settings(database_password=SecretStr(password))

    url = settings.database_url

    assert url.drivername == "postgresql+psycopg"
    assert url.password == password
    assert password not in str(url)
    assert password not in repr(url)
    assert password not in repr(settings)


def test_settings_no_lee_archivos_dotenv() -> None:
    assert Settings.model_config.get("env_file") is None


def test_database_password_nunca_aparece_en_error_de_validacion() -> None:
    password = "secreto-db-de-prueba"

    with pytest.raises(ValidationError) as error:
        crear_settings(database_password=SecretStr(password), database_port="invalido")

    assert password not in str(error.value)


def test_cooldown_de_reenvio_ausente_usa_60_segundos() -> None:
    settings = crear_settings()

    assert settings.activacion_reenvio_cooldown_segundos == 60


def test_cooldown_de_reenvio_acepta_valor_configurado() -> None:
    settings = crear_settings(activacion_reenvio_cooldown_segundos="15")

    assert settings.activacion_reenvio_cooldown_segundos == 15


def test_valores_numericos_citados_se_convierten_a_tipos_validos() -> None:
    settings = crear_settings(
        session_duration_minutes="240",
        activacion_reenvio_cooldown_segundos="90",
        activation_token_ttl_hours="24",
        activation_challenge_ttl_minutes="15",
    )
    smtp = cargar_configuracion_smtp(settings_smtp())

    assert settings.session_duration_minutes == 240
    assert settings.activacion_reenvio_cooldown_segundos == 90
    assert settings.activation_token_ttl_hours == 24
    assert settings.activation_challenge_ttl_minutes == 15
    assert smtp.port == 465
    assert smtp.timeout_seconds == 10.0


def test_vigencias_de_activacion_son_requeridas_sin_valores_predeterminados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ACTIVATION_TOKEN_TTL_HOURS", raising=False)
    monkeypatch.delenv("ACTIVATION_CHALLENGE_TTL_MINUTES", raising=False)
    valores = {
        "database_host": "localhost",
        "database_port": 5432,
        "database_name": "smart_parking_test",
        "database_user": "smart_parking_test",
        "database_password": SecretStr("test-db-password"),
    }
    with pytest.raises(ValidationError):
        Settings.model_validate(valores)


@pytest.mark.parametrize(
    ("campo", "valores_invalidos"),
    [
        ("activation_token_ttl_hours", ["malformado", 0, -1, 169]),
        ("activation_challenge_ttl_minutes", ["malformado", 4, 61]),
    ],
)
def test_vigencias_rechazan_valores_malformados_y_fuera_de_rango(
    campo: str,
    valores_invalidos: list[object],
) -> None:
    for valor in valores_invalidos:
        with pytest.raises(ValidationError):
            crear_settings(**{campo: valor})


def test_vigencias_aceptan_limites_configurados() -> None:
    assert (
        crear_settings(activation_token_ttl_hours="1").activation_token_ttl_hours == 1
    )
    assert (
        crear_settings(activation_token_ttl_hours="168").activation_token_ttl_hours
        == 168
    )
    assert (
        crear_settings(
            activation_challenge_ttl_minutes="5"
        ).activation_challenge_ttl_minutes
        == 5
    )
    assert (
        crear_settings(
            activation_challenge_ttl_minutes="60"
        ).activation_challenge_ttl_minutes
        == 60
    )


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("smtp_host", ""),
        ("smtp_username", ""),
        ("smtp_password", SecretStr("")),
        ("smtp_from_email", "no-es-correo"),
        ("smtp_port", "no-es-puerto"),
        ("smtp_security", "plaintext"),
        ("smtp_timeout_seconds", "0"),
    ],
)
def test_configuracion_smtp_rechaza_campo_identificado_y_sin_valores(
    campo: str,
    valor: object,
) -> None:
    settings = settings_smtp(**{campo: valor})

    with pytest.raises(ConfiguracionSMTPInvalidaError) as error:
        cargar_configuracion_smtp(settings)

    superficies = "\n".join(
        (str(error.value), repr(error.value), repr(error.value.args))
    )
    assert campo.upper() in superficies
    for marcador in SMTP_SECRET_MARKERS:
        assert marcador not in superficies
    assert "no-es-puerto" not in superficies


def test_development_none_acepta_remitente_test_y_no_conecta_en_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_smtp(
        app_environment="development",
        smtp_host="mailpit",
        smtp_port="1025",
        smtp_username="",
        smtp_password=SecretStr(""),
        smtp_from_email="no-reply@example.test",
        smtp_security="none",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)

    def fallo_si_intenta_conectar(*_args: object, **_kwargs: object) -> None:
        pytest.fail("La validación de startup no debe conectar ni enviar correo")

    monkeypatch.setattr("app.correo.smtp.smtplib.SMTP", fallo_si_intenta_conectar)
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
    configuracion = cargar_configuracion_smtp(settings)
    assert configuracion.security == "none"
    assert configuracion.username == ""
    assert configuracion.password == ""
    assert configuracion.from_email == "no-reply@example.test"


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("smtp_username", "usuario-sin-tls"),
        ("smtp_password", SecretStr(SMTP_SECRET_MARKERS[2])),
    ],
)
def test_development_none_rechaza_credenciales(
    campo: str,
    valor: object,
) -> None:
    smtp_values: dict[str, object] = {
        "smtp_security": "none",
        "smtp_username": "",
        "smtp_password": SecretStr(""),
    }
    smtp_values[campo] = valor
    settings = settings_smtp(**smtp_values)

    with pytest.raises(ConfiguracionSMTPInvalidaError) as error:
        cargar_configuracion_smtp(settings)

    assert campo.upper() in str(error.value)
    assert SMTP_SECRET_MARKERS[2] not in repr(error.value)


def test_production_none_es_rechazado() -> None:
    settings = settings_smtp(
        app_environment="production",
        smtp_security="none",
        smtp_username="",
        smtp_password=SecretStr(""),
    )

    with pytest.raises(ConfiguracionSMTPInvalidaError, match="SMTP_SECURITY"):
        cargar_configuracion_smtp(settings)


@pytest.mark.parametrize("app_environment", ["development", "production"])
def test_smtp_completo_se_valida_en_startup_sin_conexion_externa(
    app_environment: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_smtp(app_environment=app_environment)
    monkeypatch.setattr(main, "get_settings", lambda: settings)

    def fallo_si_intenta_conectar(*_args: object, **_kwargs: object) -> None:
        pytest.fail("La validación de startup no debe conectar ni enviar correo")

    monkeypatch.setattr(
        "app.correo.smtp.smtplib.SMTP_SSL",
        fallo_si_intenta_conectar,
    )
    monkeypatch.setattr(
        "app.correo.smtp.smtplib.SMTP",
        fallo_si_intenta_conectar,
    )

    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("smtp_host", ""),
        ("smtp_username", ""),
        ("smtp_password", SecretStr("")),
        ("smtp_from_email", ""),
    ],
)
def test_production_smtp_incompleto_falla_en_startup_sin_revelar_secretos(
    campo: str,
    valor: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_smtp(
        app_environment="production",
        **{campo: valor},
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)

    with pytest.raises(ConfiguracionSMTPInvalidaError) as error:
        with TestClient(main.app):
            pass

    superficies = "\n".join(
        (str(error.value), repr(error.value), repr(error.value.args))
    )
    assert campo.upper() in superficies
    for marcador in SMTP_SECRET_MARKERS:
        assert marcador not in superficies


@pytest.mark.parametrize("app_environment", ["development", "production"])
def test_consola_es_rechazada_en_todos_los_ambientes_sin_secretos(
    app_environment: str,
) -> None:
    marcadores = (*SMTP_SECRET_MARKERS, "DATABASE_PASSWORD_SENTINEL_34e1")

    with pytest.raises(ValidationError) as error:
        crear_settings(
            app_environment=app_environment,
            correo_transporte="consola",
            database_password=SecretStr(marcadores[-1]),
            smtp_host=marcadores[0],
            smtp_username=marcadores[1],
            smtp_password=SecretStr(marcadores[2]),
            smtp_from_email=marcadores[3],
        )

    superficies = "\n".join(
        (
            str(error.value),
            repr(error.value),
            repr(error.value.errors()),
        )
    )
    for marcador in marcadores:
        assert marcador not in superficies


@pytest.mark.parametrize(
    ("campo", "valor_invalido"),
    [
        ("app_environment", "testing-environment-invalid-82a4"),
        ("correo_transporte", "queue-transport-invalid-c91d"),
    ],
)
def test_settings_rechaza_ambiente_o_transporte_invalidos_sin_secretos(
    campo: str,
    valor_invalido: str,
) -> None:
    with pytest.raises(ValidationError) as error:
        crear_settings(
            **{campo: valor_invalido},
            smtp_host=SMTP_SECRET_MARKERS[0],
            smtp_username=SMTP_SECRET_MARKERS[1],
            smtp_password=SecretStr(SMTP_SECRET_MARKERS[2]),
            smtp_from_email=SMTP_SECRET_MARKERS[3],
        )

    superficies = "\n".join(
        (
            str(error.value),
            repr(error.value),
            repr(error.value.errors()),
        )
    )
    assert campo in superficies
    assert valor_invalido in superficies
    for marcador in SMTP_SECRET_MARKERS:
        assert marcador not in superficies
