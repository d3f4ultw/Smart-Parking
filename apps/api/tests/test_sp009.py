from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import get_db
from app.models import Sesion, Usuario
from app.seguridad.contrasenas import HASH_DUMMY_CONTRASENA
from app.seguridad.correos import huella_correo, normalizar_correo
from app.seguridad.limitador import (
    MAXIMO_INTENTOS_POR_CORREO,
    MAXIMO_INTENTOS_POR_ORIGEN,
)
from app.servicios.autenticacion import autenticar_admin
from app.servicios.usuarios import crear_admin
from main import app

RUTA_LOGIN = "/api/autenticacion/login"
CONTRASENA_PRUEBA = "Contrasena segura SP009 123"


def correo_de_prueba() -> str:
    return f"sp009-test-{uuid4().hex}@example.com"


def crear_usuario_activado(
    db: Session,
    *,
    correo: str | None = None,
    contrasena: str = CONTRASENA_PRUEBA,
) -> Usuario:
    resultado = crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo or correo_de_prueba(),
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


def test_login_valido_de_admin_activado_conserva_respuesta_minima(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_activado(db)
    hash_original = usuario.contrasena_hash

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
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Sesion)) == 1
    usuario_persistido = db.get(Usuario, usuario.id)
    assert usuario_persistido is not None
    assert usuario_persistido.contrasena_hash == hash_original


def test_login_normaliza_correo_sin_recortar_la_contrasena(
    db: Session,
    client: TestClient,
) -> None:
    correo = correo_de_prueba()
    usuario = crear_usuario_activado(db, correo=correo)

    respuesta = client.post(
        RUTA_LOGIN,
        json={
            "correo": f"  {correo.upper()}  ",
            "contrasena": CONTRASENA_PRUEBA,
        },
    )

    assert respuesta.status_code == 200
    assert usuario.correo == normalizar_correo(correo)


@pytest.mark.parametrize(
    ("estado", "contrasena_enviada"),
    [
        ("desconocido", CONTRASENA_PRUEBA),
        ("contrasena_incorrecta", "Contrasena equivocada SP009"),
        ("no_verificado", CONTRASENA_PRUEBA),
        ("inactivo", CONTRASENA_PRUEBA),
        ("debe_cambiar_contrasena", CONTRASENA_PRUEBA),
    ],
)
def test_login_rechaza_todos_los_estados_con_el_mismo_401(
    db: Session,
    client: TestClient,
    estado: str,
    contrasena_enviada: str,
) -> None:
    correo = correo_de_prueba()
    if estado == "desconocido":
        usuario = None
    else:
        usuario = crear_usuario_activado(db, correo=correo)
        if estado == "no_verificado":
            usuario.correo_verificado = False
            db.commit()
        elif estado == "inactivo":
            usuario.esta_activo = False
            db.commit()
        elif estado == "debe_cambiar_contrasena":
            usuario.debe_cambiar_contrasena = True
            db.commit()
        db.rollback()

    respuesta = client.post(
        RUTA_LOGIN,
        json={"correo": correo, "contrasena": contrasena_enviada},
    )

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "Credenciales invalidas"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert correo not in respuesta.text
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0
    if usuario is not None:
        db.rollback()
        assert db.get(Usuario, usuario.id) is not None


def test_login_conserva_espacios_intencionales_de_la_contrasena(
    db: Session,
    client: TestClient,
) -> None:
    contrasena = "  Contrasena con espacios SP009  "
    usuario = crear_usuario_activado(db, contrasena=contrasena)

    respuesta = client.post(
        RUTA_LOGIN,
        json={"correo": usuario.correo, "contrasena": contrasena},
    )

    assert respuesta.status_code == 200


def test_cuenta_inexistente_ejecuta_verificacion_dummy_argon2(db: Session) -> None:
    contrasena = "Contrasena inexistente SP009"

    with patch(
        "app.servicios.autenticacion.verificar_contrasena",
        return_value=False,
    ) as verificar:
        resultado = autenticar_admin(
            db,
            correo=correo_de_prueba(),
            contrasena=contrasena,
        )

    assert resultado is False
    verificar.assert_called_once_with(contrasena, HASH_DUMMY_CONTRASENA)


def test_cuenta_no_utilizable_tambien_ejecuta_verificacion_dummy_argon2(
    db: Session,
) -> None:
    usuario = crear_usuario_activado(db)
    usuario.esta_activo = False
    db.commit()
    db.rollback()

    contrasena = "Contrasena cuenta inactiva SP009"
    with patch(
        "app.servicios.autenticacion.verificar_contrasena",
        return_value=False,
    ) as verificar:
        resultado = autenticar_admin(
            db,
            correo=usuario.correo,
            contrasena=contrasena,
        )

    assert resultado is False
    verificar.assert_called_once_with(contrasena, HASH_DUMMY_CONTRASENA)


def test_limiter_recibe_solo_la_huella_sha256_del_correo(
    client: TestClient,
) -> None:
    correo = "admin.sp009@example.com"
    with (
        patch(
            "app.api.rutas.autenticacion.limitador_autenticacion.permitir"
        ) as permitir,
        patch("app.api.rutas.autenticacion.crear_sesion_usuario", return_value=None),
    ):
        permitir.return_value = True
        respuesta = client.post(
            RUTA_LOGIN,
            json={"correo": f"  {correo.upper()}  ", "contrasena": CONTRASENA_PRUEBA},
        )

    assert respuesta.status_code == 401
    assert permitir.call_args.args[1] == huella_correo(correo)
    assert correo not in permitir.call_args.args


def test_rate_limit_por_origen_es_independiente_del_correo(client: TestClient) -> None:
    with patch(
        "app.api.rutas.autenticacion.crear_sesion_usuario",
        return_value=None,
    ) as autenticar:
        respuestas = [
            client.post(
                RUTA_LOGIN,
                json={
                    "correo": f"origen-{indice}@example.com",
                    "contrasena": CONTRASENA_PRUEBA,
                },
            )
            for indice in range(MAXIMO_INTENTOS_POR_ORIGEN + 1)
        ]

    assert [respuesta.status_code for respuesta in respuestas[:-1]] == [
        401
    ] * MAXIMO_INTENTOS_POR_ORIGEN
    assert respuestas[-1].status_code == 429
    assert autenticar.call_count == MAXIMO_INTENTOS_POR_ORIGEN
    assert respuestas[-1].json() == {"detail": "Demasiados intentos"}
    assert respuestas[-1].headers["cache-control"] == "no-store"


def test_rate_limit_por_huella_de_correo_es_independiente_del_origen(
    client: TestClient,
) -> None:
    correo = "repetido.sp009@example.com"
    origenes = [f"origen-correo-{indice}" for indice in range(6)]
    with (
        patch(
            "app.api.rutas.autenticacion._obtener_origen",
            side_effect=origenes,
        ),
        patch(
            "app.api.rutas.autenticacion.crear_sesion_usuario",
            return_value=None,
        ) as autenticar,
    ):
        respuestas = [
            client.post(
                RUTA_LOGIN,
                json={"correo": correo, "contrasena": CONTRASENA_PRUEBA},
            )
            for _ in origenes
        ]

    assert [respuesta.status_code for respuesta in respuestas] == [401] * 5 + [429]
    assert autenticar.call_count == MAXIMO_INTENTOS_POR_CORREO
    assert respuestas[-1].json() == {"detail": "Demasiados intentos"}


def test_x_forwarded_for_no_cambia_el_origen_del_rate_limit(client: TestClient) -> None:
    with patch(
        "app.api.rutas.autenticacion.crear_sesion_usuario",
        return_value=None,
    ) as autenticar:
        respuestas = [
            client.post(
                RUTA_LOGIN,
                json={
                    "correo": f"xff-{indice}@example.com",
                    "contrasena": CONTRASENA_PRUEBA,
                },
                headers={"X-Forwarded-For": f"198.51.100.{indice + 1}"},
            )
            for indice in range(MAXIMO_INTENTOS_POR_ORIGEN + 1)
        ]

    assert [respuesta.status_code for respuesta in respuestas[:-1]] == [
        401
    ] * MAXIMO_INTENTOS_POR_ORIGEN
    assert respuestas[-1].status_code == 429
    assert autenticar.call_count == MAXIMO_INTENTOS_POR_ORIGEN


@pytest.mark.parametrize(
    "payload",
    [
        {"correo": "no-es-un-correo", "contrasena": CONTRASENA_PRUEBA},
        {"correo": "admin@example.com", "contrasena": ""},
        {
            "correo": "admin@example.com",
            "contrasena": "x" * 129,
        },
        {
            "correo": "x" * 321,
            "contrasena": CONTRASENA_PRUEBA,
        },
        {
            "correo": "admin@example.com",
            "contrasena": CONTRASENA_PRUEBA,
            "secreto": "no-debe-aceptarse",
        },
    ],
)
def test_solicitud_malformada_es_422_generica_y_no_cacheable(
    client: TestClient,
    payload: dict[str, str],
) -> None:
    respuesta = client.post(RUTA_LOGIN, json=payload)

    assert respuesta.status_code == 422
    assert respuesta.json() == {"detail": "Solicitud invalida"}
    assert respuesta.headers["cache-control"] == "no-store"
    for valor in payload.values():
        if valor:
            assert valor not in respuesta.text


def test_error_sqlalchemy_es_500_generico_y_no_cacheable(client: TestClient) -> None:
    correo = "sql.sp009@example.com"
    with patch(
        "app.api.rutas.autenticacion.crear_sesion_usuario",
        side_effect=SQLAlchemyError("fallo de prueba"),
    ):
        respuesta = client.post(
            RUTA_LOGIN,
            json={"correo": correo, "contrasena": CONTRASENA_PRUEBA},
        )

    assert respuesta.status_code == 500
    assert respuesta.json() == {"detail": "Error interno"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert correo not in respuesta.text


def test_respuesta_429_no_revela_estado_ni_credenciales(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    correo = "rate.sp009@example.com"
    contrasena = "Contrasena rate SP009"
    caplog.set_level("INFO")
    with (
        patch(
            "app.api.rutas.autenticacion._obtener_origen",
            side_effect=["origen-rate"] * (MAXIMO_INTENTOS_POR_CORREO + 1),
        ),
        patch("app.api.rutas.autenticacion.crear_sesion_usuario", return_value=None),
    ):
        respuestas = [
            client.post(
                RUTA_LOGIN,
                json={"correo": correo, "contrasena": contrasena},
            )
            for _ in range(MAXIMO_INTENTOS_POR_CORREO + 1)
        ]

    respuesta = respuestas[-1]
    assert respuesta.status_code == 429
    assert respuesta.json() == {"detail": "Demasiados intentos"}
    assert correo not in respuesta.text
    assert contrasena not in respuesta.text
    assert correo not in caplog.text
    assert contrasena not in caplog.text
