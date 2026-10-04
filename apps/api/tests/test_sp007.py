from __future__ import annotations

import logging
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import call, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.api.rutas.activaciones import (
    CODIGO_ACTIVACION_NO_DISPONIBLE,
    DETALLE_ACTIVACION_NO_DISPONIBLE,
)
from app.core.database import get_db
from app.models import Usuario
from app.seguridad.activaciones import hash_token_activacion
from app.seguridad.contrasenas import HASH_DUMMY_CODIGO, HASH_DUMMY_CONTRASENA
from app.seguridad.limitador import (
    MAXIMO_INTENTOS_POR_ORIGEN,
    MAXIMO_INTENTOS_POR_TOKEN,
    LimitadorActivaciones,
    LimitadorVentanaDeslizante,
)
from app.servicios.activaciones import (
    ActivacionNoDisponible,
    activar_cuenta_manual,
    activar_cuenta_temporal,
    crear_activacion,
)
from app.servicios.usuarios import crear_admin
from main import app

LOGGER_NAME = "app.api.rutas.activaciones"


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


def correo_de_prueba() -> str:
    return f"sp007-test-{uuid4().hex}@example.com"


def crear_usuario_manual(db: Session) -> Usuario:
    resultado = crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo_de_prueba(),
        contrasena="Contrasena manual SP007 123",
        confirmacion_contrasena="Contrasena manual SP007 123",
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


def crear_activacion_de_prueba(db: Session, usuario: Usuario):
    resultado = crear_activacion(db, usuario.id)
    db.rollback()
    return resultado


def payload_manual(token: str) -> dict[str, str]:
    return {"token": token, "codigo": "123456"}


def test_limitador_por_origen() -> None:
    limitador = LimitadorActivaciones(limite_token=100)

    for indice in range(MAXIMO_INTENTOS_POR_ORIGEN):
        assert limitador.permitir(
            "origen-prueba",
            hash_token_activacion(f"token-{indice}"),
            ahora=0,
        )

    assert not limitador.permitir(
        "origen-prueba",
        hash_token_activacion("token-extra"),
        ahora=0,
    )
    assert limitador.permitir(
        "otro-origen",
        hash_token_activacion("token-otro-origen"),
        ahora=0,
    )


def test_limitador_por_huella_de_token() -> None:
    limitador = LimitadorActivaciones(limite_origen=100)
    huella = hash_token_activacion("token-repetido")

    for indice in range(MAXIMO_INTENTOS_POR_TOKEN):
        assert limitador.permitir(f"origen-{indice}", huella, ahora=0)

    assert not limitador.permitir("origen-extra", huella, ahora=0)
    assert limitador.permitir(
        "origen-extra",
        hash_token_activacion("token-diferente"),
        ahora=0,
    )


def test_limites_de_origen_y_token_son_independientes() -> None:
    limitador = LimitadorActivaciones(limite_origen=2, limite_token=2)
    huella = hash_token_activacion("token-compartido")

    assert limitador.permitir("origen-1", huella, ahora=0)
    assert limitador.permitir("origen-2", huella, ahora=0)
    assert not limitador.permitir("origen-3", huella, ahora=0)

    assert limitador.permitir(
        "origen-1",
        hash_token_activacion("token-nuevo"),
        ahora=0,
    )
    assert not limitador.permitir(
        "origen-1",
        hash_token_activacion("token-tercero"),
        ahora=0,
    )


def test_limitador_concurrente_es_thread_safe() -> None:
    limitador = LimitadorVentanaDeslizante(limite=5, ventana_segundos=300)

    def intentar(_indice: int) -> bool:
        return limitador.permitir("misma-clave", ahora=0)

    with ThreadPoolExecutor(max_workers=20) as executor:
        resultados = list(executor.map(intentar, range(32)))

    assert sum(resultados) == 5


def test_ventana_permite_nuevo_intento_y_limpia_entradas_expiradas() -> None:
    limitador = LimitadorVentanaDeslizante(limite=1, ventana_segundos=300)

    assert limitador.permitir("clave", ahora=0)
    assert not limitador.permitir("clave", ahora=1)
    assert limitador.permitir("otra-clave", ahora=301)
    assert limitador.cantidad_claves() == 1
    assert limitador.permitir("clave", ahora=301)


def test_429_por_token_no_consulta_el_servicio(
    client: TestClient,
) -> None:
    token = "token-rate-limit-sp007"
    with patch("app.api.rutas.activaciones.activar_cuenta_manual") as activar:
        respuestas = [
            client.post(
                "/api/autenticacion/activar/manual",
                json=payload_manual(token),
            )
            for _ in range(MAXIMO_INTENTOS_POR_TOKEN + 1)
        ]

    assert [respuesta.status_code for respuesta in respuestas] == [
        200,
        200,
        200,
        200,
        200,
        429,
    ]
    assert activar.call_count == MAXIMO_INTENTOS_POR_TOKEN
    assert respuestas[-1].json() == {"detail": "Demasiados intentos"}
    assert respuestas[-1].headers["cache-control"] == "no-store"


def test_la_ruta_entrega_al_limiter_solo_la_huella_sha256(
    client: TestClient,
) -> None:
    token = "token-crudo-que-no-debe-llegar-al-limiter"

    with (
        patch("app.api.rutas.activaciones.limitador_activaciones.permitir") as permitir,
        patch("app.api.rutas.activaciones.activar_cuenta_manual"),
    ):
        permitir.return_value = True
        respuesta = client.post(
            "/api/autenticacion/activar/manual",
            json=payload_manual(token),
        )

    assert respuesta.status_code == 200
    assert permitir.call_args.args[1] == hash_token_activacion(token)
    assert token not in permitir.call_args.args


def test_rate_limit_por_origen_ignora_x_forwarded_for(
    client: TestClient,
) -> None:
    with patch("app.api.rutas.activaciones.activar_cuenta_manual") as activar:
        respuestas = [
            client.post(
                "/api/autenticacion/activar/manual",
                json=payload_manual(f"token-origen-{indice}"),
                headers={"X-Forwarded-For": f"198.51.100.{indice + 1}"},
            )
            for indice in range(MAXIMO_INTENTOS_POR_ORIGEN + 1)
        ]

    assert [respuesta.status_code for respuesta in respuestas[:-1]] == [
        200
    ] * MAXIMO_INTENTOS_POR_ORIGEN
    assert respuestas[-1].status_code == 429
    assert activar.call_count == MAXIMO_INTENTOS_POR_ORIGEN


def test_token_valido_e_invalido_tienen_la_misma_politica_de_rate_limit(
    client: TestClient,
) -> None:
    token_valido = "token-que-el-servicio-acepta"
    token_invalido = "token-que-el-servicio-rechaza"

    def servicio(
        _db: Session,
        *,
        token: str,
        codigo: str,
    ) -> None:
        del codigo
        if token != token_valido:
            raise ActivacionNoDisponible

    with patch(
        "app.api.rutas.activaciones.activar_cuenta_manual",
        side_effect=servicio,
    ):
        respuestas_validas = [
            client.post(
                "/api/autenticacion/activar/manual",
                json=payload_manual(token_valido),
            )
            for _ in range(MAXIMO_INTENTOS_POR_TOKEN + 1)
        ]
        respuestas_invalidas = [
            client.post(
                "/api/autenticacion/activar/manual",
                json=payload_manual(token_invalido),
            )
            for _ in range(MAXIMO_INTENTOS_POR_TOKEN + 1)
        ]

    assert [respuesta.status_code for respuesta in respuestas_validas] == [
        200,
        200,
        200,
        200,
        200,
        429,
    ]
    assert [respuesta.status_code for respuesta in respuestas_invalidas] == [
        404,
        404,
        404,
        404,
        404,
        429,
    ]


def test_429_no_revela_estado_ni_secretos(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = "token-secreto-rate-limit-sp007"
    codigo = "654321"
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    with patch("app.api.rutas.activaciones.activar_cuenta_manual"):
        respuestas = [
            client.post(
                "/api/autenticacion/activar/manual",
                json={"token": token, "codigo": codigo},
            )
            for _ in range(MAXIMO_INTENTOS_POR_TOKEN + 1)
        ]

    respuesta = respuestas[-1]

    assert respuesta.status_code == 429
    assert respuesta.json() == {"detail": "Demasiados intentos"}
    assert token not in respuesta.text
    assert codigo not in respuesta.text
    assert token not in caplog.text
    assert codigo not in caplog.text


@pytest.mark.parametrize(
    ("ruta", "payload", "nombre_servicio"),
    [
        (
            "/api/autenticacion/activar/manual",
            {"token": "token-cache-manual", "codigo": "123456"},
            "activar_cuenta_manual",
        ),
        (
            "/api/autenticacion/activar/temporal",
            {
                "token": "token-cache-temporal",
                "codigo": "123456",
                "contrasena_temporal": "temporal-segura",
                "nueva_contrasena": "nueva-contrasena-segura",
                "confirmar_contrasena": "nueva-contrasena-segura",
            },
            "activar_cuenta_temporal",
        ),
    ],
)
def test_respuestas_exitosas_no_son_cacheables(
    client: TestClient,
    ruta: str,
    payload: dict[str, str],
    nombre_servicio: str,
) -> None:
    with patch(f"app.api.rutas.activaciones.{nombre_servicio}"):
        respuesta = client.post(ruta, json=payload)

    assert respuesta.status_code == 200
    assert respuesta.headers["cache-control"] == "no-store"


def test_404_y_422_tambien_incluyen_no_store(client: TestClient) -> None:
    with patch(
        "app.api.rutas.activaciones.activar_cuenta_manual",
        side_effect=ActivacionNoDisponible,
    ):
        respuesta_404 = client.post(
            "/api/autenticacion/activar/manual",
            json=payload_manual("token-404-cache"),
        )

    respuesta_422 = client.post(
        "/api/autenticacion/activar/manual",
        json={"token": "token-422-cache", "codigo": "12345"},
    )

    assert respuesta_404.status_code == 404
    assert respuesta_404.json() == {
        "detail": {
            "code": CODIGO_ACTIVACION_NO_DISPONIBLE,
            "message": DETALLE_ACTIVACION_NO_DISPONIBLE,
        }
    }
    assert respuesta_404.headers["cache-control"] == "no-store"
    assert respuesta_422.status_code == 422
    assert respuesta_422.headers["cache-control"] == "no-store"


def test_error_de_persistencia_es_seguro_y_se_registra(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = "token-persistencia-secreto"
    codigo = "codigo-persistencia-secreto"
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    with patch(
        "app.api.rutas.activaciones.activar_cuenta_manual",
        side_effect=SQLAlchemyError(f"token={token} codigo={codigo}"),
    ):
        respuesta = client.post(
            "/api/autenticacion/activar/manual",
            json={"token": token, "codigo": "123456"},
        )

    assert respuesta.status_code == 500
    assert respuesta.json() == {"detail": "Error interno"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert token not in respuesta.text
    assert token not in caplog.text
    assert codigo not in caplog.text
    assert "Error interno de persistencia durante activacion" in caplog.text


def test_logs_de_exito_y_rechazo_no_contienen_secretos(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    token_exitoso = "token-log-exitoso-secreto"
    codigo_exitoso = "111111"
    token_rechazado = "token-log-rechazado-secreto"
    codigo_rechazado = "222222"
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    with patch("app.api.rutas.activaciones.activar_cuenta_manual"):
        respuesta_exitosa = client.post(
            "/api/autenticacion/activar/manual",
            json={"token": token_exitoso, "codigo": codigo_exitoso},
        )

    with patch(
        "app.api.rutas.activaciones.activar_cuenta_manual",
        side_effect=ActivacionNoDisponible,
    ):
        respuesta_rechazada = client.post(
            "/api/autenticacion/activar/manual",
            json={"token": token_rechazado, "codigo": codigo_rechazado},
        )

    assert respuesta_exitosa.status_code == 200
    assert respuesta_rechazada.status_code == 404
    assert "Activacion exitosa" in caplog.text
    assert "Activacion rechazada" in caplog.text
    for secreto in (
        token_exitoso,
        codigo_exitoso,
        token_rechazado,
        codigo_rechazado,
    ):
        assert secreto not in caplog.text


def test_camino_manual_inexistente_hace_dummy_argon2(db: Session) -> None:
    usuario = crear_usuario_manual(db)
    crear_activacion_de_prueba(db, usuario)

    with patch(
        "app.servicios.activaciones.verificar_contrasena",
        return_value=False,
    ) as verificar:
        with pytest.raises(ActivacionNoDisponible):
            activar_cuenta_manual(
                db,
                token="token-inexistente-sp007",
                codigo="123456",
            )

    assert verificar.call_args_list == [call("123456", HASH_DUMMY_CODIGO)]


def test_camino_temporal_inexistente_hace_dummy_argon2_para_codigo_y_contrasena(
    db: Session,
) -> None:
    usuario, _contrasena_temporal = crear_usuario_temporal(db)
    crear_activacion_de_prueba(db, usuario)

    with patch(
        "app.servicios.activaciones.verificar_contrasena",
        return_value=False,
    ) as verificar:
        with pytest.raises(ActivacionNoDisponible):
            activar_cuenta_temporal(
                db,
                token="token-inexistente-sp007",
                codigo="123456",
                contrasena_temporal="temporal-secreta",
                nueva_contrasena="Nueva contrasena segura SP007",
                confirmar_contrasena="Nueva contrasena segura SP007",
            )

    assert verificar.call_args_list == [
        call("123456", HASH_DUMMY_CODIGO),
        call("temporal-secreta", HASH_DUMMY_CONTRASENA),
    ]
