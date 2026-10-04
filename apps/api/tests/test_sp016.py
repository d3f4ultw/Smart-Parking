from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.api.rutas.activaciones import (
    CODIGO_ACTIVACION_NO_DISPONIBLE,
    DETALLE_ACTIVACION_NO_DISPONIBLE,
)
from app.core.config import Settings
from app.core.database import get_db
from app.models import ActivacionCuenta, Sesion, Usuario
from app.servicios.activaciones import (
    ActivacionNoDisponible,
    activar_cuenta_manual,
    crear_activacion,
    prevalidar_activacion,
    reenviar_activacion,
)
from app.servicios.usuarios import crear_admin
from main import app


def correo_de_prueba() -> str:
    return f"sp016-test-{uuid4().hex}@example.com"


def cooldown_de_prueba() -> int:
    return Settings(
        **{
            "_env_file": None,
            "database_host": "localhost",
            "database_port": 5432,
            "database_name": "unused",
            "database_user": "unused",
            "database_password": "test-db-password",
            "activation_token_ttl_hours": 24,
            "activation_challenge_ttl_minutes": 15,
        }
    ).activacion_reenvio_cooldown_segundos


def crear_usuario_manual(db: Session) -> Usuario:
    resultado = crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo_de_prueba(),
        contrasena="Contrasena manual SP016 123",
        confirmacion_contrasena="Contrasena manual SP016 123",
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


def crear_activacion_de_prueba(
    db: Session,
    usuario: Usuario,
    *,
    ahora: datetime | None = None,
):
    resultado = crear_activacion(db, usuario.id, ahora=ahora)
    db.rollback()
    return resultado


@pytest.fixture
def client(database_url: URL) -> Generator[TestClient]:
    test_engine = create_engine(database_url, pool_pre_ping=True)
    test_session_factory = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db():
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


def test_prevalidacion_manual_devuelve_solo_el_modo_y_no_muta(
    db: Session,
) -> None:
    ahora = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario, ahora=ahora)
    hash_original = usuario.contrasena_hash

    assert prevalidar_activacion(db, token=resultado.token, ahora=ahora) == "manual"
    assert prevalidar_activacion(db, token=resultado.token, ahora=ahora) == "manual"

    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    activacion_persistida = db.get(ActivacionCuenta, resultado.activacion.id)
    assert usuario_persistido is not None
    assert activacion_persistida is not None
    assert usuario_persistido.contrasena_hash == hash_original
    assert usuario_persistido.correo_verificado is False
    assert activacion_persistida.consumido_en is None
    assert activacion_persistida.expira_en == resultado.activacion.expira_en
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0


def test_endpoint_prevalidacion_temporal_no_devuelve_credenciales(
    db: Session,
    client: TestClient,
) -> None:
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario)

    response = client.post(
        "/api/autenticacion/activacion/prevalidar",
        json={"token": resultado.token},
    )

    assert response.status_code == 200
    assert response.json() == {"modo": "temporal"}
    assert resultado.token not in response.text
    assert contrasena_temporal not in response.text


@pytest.mark.parametrize(
    "estado", ["aleatorio", "expirada", "consumida", "reemplazada"]
)
def test_endpoint_prevalidacion_rechaza_estados_no_utilizables(
    db: Session,
    client: TestClient,
    estado: str,
) -> None:
    ahora = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario, ahora=ahora)

    if estado == "aleatorio":
        token = f"{resultado.token}-inexistente"
    elif estado == "expirada":
        activacion = db.get(ActivacionCuenta, resultado.activacion.id)
        assert activacion is not None
        activacion.expira_en = ahora - timedelta(seconds=1)
        db.commit()
        db.rollback()
        token = resultado.token
    elif estado == "consumida":
        activacion = db.get(ActivacionCuenta, resultado.activacion.id)
        assert activacion is not None
        activacion.consumido_en = ahora
        db.commit()
        db.rollback()
        token = resultado.token
    else:
        resultado.activacion.creado_en = ahora
        db.commit()
        db.rollback()
        reemplazo = reenviar_activacion(
            db,
            usuario.correo,
            cooldown_segundos=cooldown_de_prueba(),
            ahora=ahora + timedelta(seconds=61),
        )
        assert reemplazo is not None
        token = resultado.token

    response = client.post(
        "/api/autenticacion/activacion/prevalidar",
        json={"token": token},
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "code": CODIGO_ACTIVACION_NO_DISPONIBLE,
            "message": DETALLE_ACTIVACION_NO_DISPONIBLE,
        }
    }
    assert token not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"token": ""},
        {"token": "T" * 513},
        {"token": "token-estructural", "modo": "manual"},
    ],
)
def test_endpoint_prevalidacion_rechaza_payload_malformado_sin_reflejarlo(
    client: TestClient,
    payload: dict[str, str],
) -> None:
    response = client.post(
        "/api/autenticacion/activacion/prevalidar",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Solicitud invalida"}
    for value in payload.values():
        if value:
            assert value not in response.text


def test_prevalidacion_no_consumida_permite_activacion_final(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario)

    prevalidacion = client.post(
        "/api/autenticacion/activacion/prevalidar",
        json={"token": resultado.token},
    )
    activacion = client.post(
        "/api/autenticacion/activar/manual",
        json={"token": resultado.token, "codigo": resultado.codigo},
    )

    assert prevalidacion.status_code == 200
    assert prevalidacion.json() == {"modo": "manual"}
    assert activacion.status_code == 200
    assert activacion.json() == {"estado": "activada"}


def test_activacion_final_revalida_expiracion_despues_de_prevalidar(
    db: Session,
) -> None:
    inicio = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario, ahora=inicio)

    assert prevalidar_activacion(db, token=resultado.token, ahora=inicio) == "manual"
    with pytest.raises(ActivacionNoDisponible):
        activar_cuenta_manual(
            db,
            token=resultado.token,
            codigo=resultado.codigo,
            ahora=inicio + timedelta(minutes=15),
        )

    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    activacion_persistida = db.get(ActivacionCuenta, resultado.activacion.id)
    assert usuario_persistido is not None
    assert activacion_persistida is not None
    assert usuario_persistido.correo_verificado is False
    assert activacion_persistida.consumido_en is None


def test_prevalidacion_reemplazada_no_invalida_el_nuevo_token(
    db: Session,
) -> None:
    inicio = datetime(2026, 9, 28, 13, 0, tzinfo=UTC)
    usuario = crear_usuario_manual(db)
    primera = crear_activacion_de_prueba(db, usuario, ahora=inicio)
    primera.activacion.creado_en = inicio
    db.commit()
    db.rollback()

    segunda = reenviar_activacion(
        db,
        usuario.correo,
        cooldown_segundos=cooldown_de_prueba(),
        ahora=inicio + timedelta(seconds=61),
    )
    assert segunda is not None

    with pytest.raises(ActivacionNoDisponible):
        prevalidar_activacion(db, token=primera.token, ahora=inicio)
    assert prevalidar_activacion(db, token=segunda.token, ahora=inicio) == "manual"
