from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.api.rutas.activaciones import (
    CODIGO_ACTIVACION_NO_DISPONIBLE,
    CODIGO_DATOS_ACTIVACION_INVALIDOS,
)
from app.core.database import get_db
from app.models import ActivacionCuenta, Sesion, Usuario
from app.servicios.activaciones import (
    ActivacionNoDisponible,
    DatosActivacionInvalidos,
    activar_cuenta_manual,
    crear_activacion,
)
from app.servicios.usuarios import crear_admin
from main import app


def correo_de_prueba() -> str:
    return f"sp005-test-{uuid4().hex}@example.com"


def crear_usuario_manual(db: Session) -> Usuario:
    resultado = crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo_de_prueba(),
        contrasena="Contrasena manual SP005 123",
        confirmacion_contrasena="Contrasena manual SP005 123",
    )
    return resultado.usuario


def crear_usuario_temporal(db: Session) -> Usuario:
    resultado = crear_admin(
        db,
        nombre="Grace",
        apellido_paterno="Hopper",
        apellido_materno="Murray",
        correo=correo_de_prueba(),
        usar_contrasena_temporal=True,
    )
    return resultado.usuario


def crear_activacion_de_prueba(
    db: Session,
    *,
    usuario: Usuario,
    ahora: datetime | None = None,
):
    resultado = crear_activacion(db, usuario.id, ahora=ahora)
    db.rollback()
    return resultado


def obtener_usuario(db: Session, usuario_id: int) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    assert usuario is not None
    return usuario


def obtener_activacion(db: Session, activacion_id: int) -> ActivacionCuenta:
    activacion = db.get(ActivacionCuenta, activacion_id)
    assert activacion is not None
    return activacion


@pytest.fixture
def client(database_url: URL):
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


def test_activacion_manual_cambia_solo_estado_de_correo_y_consumo(
    db: Session,
) -> None:
    ahora = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario, ahora=ahora)
    contrasena_hash_original = usuario.contrasena_hash

    activar_cuenta_manual(
        db,
        token=resultado.token,
        codigo=resultado.codigo,
        ahora=ahora,
    )

    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    activacion_persistida = db.get(ActivacionCuenta, resultado.activacion.id)
    assert usuario_persistido is not None
    assert activacion_persistida is not None
    assert usuario_persistido.correo_verificado is True
    assert usuario_persistido.esta_activo is True
    assert usuario_persistido.debe_cambiar_contrasena is False
    assert usuario_persistido.contrasena_hash == contrasena_hash_original
    assert activacion_persistida.consumido_en == ahora
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0


def test_token_incorrecto_no_cambia_estado(db: Session) -> None:
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    hash_original = usuario.contrasena_hash

    with pytest.raises(ActivacionNoDisponible) as error:
        activar_cuenta_manual(
            db,
            token=f"{resultado.token}-incorrecto",
            codigo=resultado.codigo,
        )

    assert str(error.value) == "Activacion no disponible"
    db.rollback()
    usuario_persistido = obtener_usuario(db, usuario.id)
    activacion_persistida = obtener_activacion(db, resultado.activacion.id)
    assert usuario_persistido.correo_verificado is False
    assert usuario_persistido.contrasena_hash == hash_original
    assert activacion_persistida.consumido_en is None


def test_codigo_incorrecto_no_cambia_estado(db: Session) -> None:
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    codigo_incorrecto = str((int(resultado.codigo) + 1) % 1_000_000).zfill(6)

    with pytest.raises(DatosActivacionInvalidos):
        activar_cuenta_manual(
            db,
            token=resultado.token,
            codigo=codigo_incorrecto,
        )

    db.rollback()
    assert obtener_usuario(db, usuario.id).correo_verificado is False
    assert obtener_activacion(db, resultado.activacion.id).consumido_en is None


def test_activacion_expirada_incluye_el_limite_exactamente(db: Session) -> None:
    inicio = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    usuario_expirado = crear_usuario_manual(db)
    resultado_expirado = crear_activacion_de_prueba(
        db,
        usuario=usuario_expirado,
        ahora=inicio,
    )

    with pytest.raises(ActivacionNoDisponible):
        activar_cuenta_manual(
            db,
            token=resultado_expirado.token,
            codigo=resultado_expirado.codigo,
            ahora=inicio + timedelta(minutes=15),
        )

    usuario_valido = crear_usuario_manual(db)
    resultado_valido = crear_activacion_de_prueba(
        db,
        usuario=usuario_valido,
        ahora=inicio,
    )
    activar_cuenta_manual(
        db,
        token=resultado_valido.token,
        codigo=resultado_valido.codigo,
        ahora=inicio + timedelta(minutes=14, seconds=59),
    )
    db.rollback()
    assert obtener_usuario(db, usuario_valido.id).correo_verificado is True


def test_activacion_consumida_no_puede_reutilizarse(db: Session) -> None:
    ahora = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario, ahora=ahora)
    activacion = db.get(ActivacionCuenta, resultado.activacion.id)
    assert activacion is not None
    activacion.consumido_en = ahora
    db.commit()
    db.rollback()

    with pytest.raises(ActivacionNoDisponible):
        activar_cuenta_manual(
            db,
            token=resultado.token,
            codigo=resultado.codigo,
            ahora=ahora,
        )

    db.rollback()
    assert obtener_usuario(db, usuario.id).correo_verificado is False


@pytest.mark.parametrize("campo", ["esta_activo", "correo_verificado"])
def test_usuario_inactivo_o_ya_verificado_no_puede_activarse(
    db: Session,
    campo: str,
) -> None:
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    setattr(usuario, campo, False if campo == "esta_activo" else True)
    db.commit()
    db.rollback()

    with pytest.raises(ActivacionNoDisponible):
        activar_cuenta_manual(
            db,
            token=resultado.token,
            codigo=resultado.codigo,
        )

    db.rollback()
    assert obtener_activacion(db, resultado.activacion.id).consumido_en is None


def test_usuario_de_contrasena_temporal_se_reserva_para_sp006(db: Session) -> None:
    usuario = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    hash_original = usuario.contrasena_hash

    with pytest.raises(ActivacionNoDisponible):
        activar_cuenta_manual(
            db,
            token=resultado.token,
            codigo=resultado.codigo,
        )

    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    assert usuario_persistido is not None
    assert usuario_persistido.debe_cambiar_contrasena is True
    assert usuario_persistido.correo_verificado is False
    assert usuario_persistido.contrasena_hash == hash_original
    assert obtener_activacion(db, resultado.activacion.id).consumido_en is None


def test_relacion_de_usuario_inexistente_falla_de_forma_segura(db: Session) -> None:
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    db.rollback()
    activation = db.get(ActivacionCuenta, resultado.activacion.id)
    assert activation is not None
    db.rollback()

    with patch.object(db, "scalar", side_effect=[activation, None]):
        with pytest.raises(ActivacionNoDisponible):
            activar_cuenta_manual(
                db,
                token=resultado.token,
                codigo=resultado.codigo,
            )


def test_fallo_de_base_de_datos_hace_rollback_de_consumo(db: Session) -> None:
    ahora = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario, ahora=ahora)
    db.rollback()

    with patch.object(db, "flush", side_effect=SQLAlchemyError("fallo controlado")):
        with pytest.raises(SQLAlchemyError):
            activar_cuenta_manual(
                db,
                token=resultado.token,
                codigo=resultado.codigo,
                ahora=ahora,
            )

    db.rollback()
    assert obtener_usuario(db, usuario.id).correo_verificado is False
    assert obtener_activacion(db, resultado.activacion.id).consumido_en is None


def test_doble_consumo_secuencial_solo_permite_un_exito(db: Session) -> None:
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    activar_cuenta_manual(
        db,
        token=resultado.token,
        codigo=resultado.codigo,
    )
    db.rollback()

    with pytest.raises(ActivacionNoDisponible):
        activar_cuenta_manual(
            db,
            token=resultado.token,
            codigo=resultado.codigo,
        )

    db.rollback()
    assert obtener_usuario(db, usuario.id).correo_verificado is True
    assert (
        db.scalar(
            select(func.count())
            .select_from(ActivacionCuenta)
            .where(ActivacionCuenta.consumido_en.is_not(None))
        )
        == 1
    )


def test_consumo_concurrente_usa_bloqueo_de_fila(db: Session) -> None:
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    engine = db.get_bind()
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    barrera = Barrier(2)

    def intentar_activar() -> str:
        sesion = session_factory()
        try:
            barrera.wait(timeout=10)
            activar_cuenta_manual(
                sesion,
                token=resultado.token,
                codigo=resultado.codigo,
            )
            return "exito"
        except ActivacionNoDisponible:
            return "rechazo"
        finally:
            sesion.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        resultados = list(executor.map(lambda _: intentar_activar(), range(2)))

    assert sorted(resultados) == ["exito", "rechazo"]
    db.rollback()
    db.expire_all()
    assert obtener_usuario(db, usuario.id).correo_verificado is True
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0


def test_endpoint_manual_devuelve_contrato_minimo(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    hash_original = usuario.contrasena_hash

    response = client.post(
        "/api/autenticacion/activar/manual",
        json={"token": resultado.token, "codigo": resultado.codigo},
    )

    assert response.status_code == 200
    assert response.json() == {"estado": "activada"}
    assert resultado.token not in response.text
    assert resultado.codigo not in response.text
    db.rollback()
    db.expire_all()
    usuario_persistido = db.get(Usuario, usuario.id)
    activacion_persistida = db.get(ActivacionCuenta, resultado.activacion.id)
    assert usuario_persistido is not None
    assert activacion_persistida is not None
    assert usuario_persistido.correo_verificado is True
    assert usuario_persistido.contrasena_hash == hash_original
    assert activacion_persistida.consumido_en is not None
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0


@pytest.mark.parametrize("estado", ["desconocido", "expirada", "consumida"])
def test_endpoint_expone_404_generico_para_activaciones_no_utilizables(
    db: Session,
    client: TestClient,
    estado: str,
) -> None:
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    codigo = resultado.codigo
    if estado == "desconocido":
        token = f"{resultado.token}-otro"
    else:
        token = resultado.token
        activacion = db.get(ActivacionCuenta, resultado.activacion.id)
        assert activacion is not None
        if estado == "expirada":
            activacion.expira_en = datetime.now(UTC) - timedelta(seconds=1)
        else:
            activacion.consumido_en = datetime.now(UTC)
        db.commit()
        db.rollback()

    response = client.post(
        "/api/autenticacion/activar/manual",
        json={"token": token, "codigo": codigo},
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "code": CODIGO_ACTIVACION_NO_DISPONIBLE,
            "message": "Activacion no disponible",
        }
    }
    assert resultado.token not in response.text
    assert resultado.codigo not in response.text


def test_endpoint_codigo_incorrecto_conserva_categoria_de_credenciales_invalidas(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    codigo_incorrecto = str((int(resultado.codigo) + 1) % 1_000_000).zfill(6)

    response = client.post(
        "/api/autenticacion/activar/manual",
        json={"token": resultado.token, "codigo": codigo_incorrecto},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": CODIGO_DATOS_ACTIVACION_INVALIDOS,
            "message": "Solicitud invalida",
        }
    }
    assert resultado.token not in response.text
    assert resultado.codigo not in response.text


@pytest.mark.parametrize("modo", ["inactivo", "verificado", "temporal"])
def test_endpoint_rechaza_estado_de_usuario_con_el_mismo_404(
    db: Session,
    client: TestClient,
    modo: str,
) -> None:
    if modo == "temporal":
        usuario = crear_usuario_temporal(db)
    else:
        usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    if modo == "inactivo":
        usuario.esta_activo = False
    elif modo == "verificado":
        usuario.correo_verificado = True
    db.commit()
    db.rollback()

    response = client.post(
        "/api/autenticacion/activar/manual",
        json={"token": resultado.token, "codigo": resultado.codigo},
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "code": CODIGO_ACTIVACION_NO_DISPONIBLE,
            "message": "Activacion no disponible",
        }
    }
    assert resultado.token not in response.text
    assert resultado.codigo not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"token": "", "codigo": "123456"},
        {"token": "T" * 513, "codigo": "123456"},
        {"token": "token", "codigo": "12345"},
        {"token": "token", "codigo": "1234567"},
        {"token": "token", "codigo": "abcdef"},
        {"token": "token", "codigo": " 123456"},
    ],
)
def test_payload_malformado_no_devuelve_secretos(
    client: TestClient,
    payload: dict[str, str],
) -> None:
    response = client.post("/api/autenticacion/activar/manual", json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": "Solicitud invalida"}
    for value in payload.values():
        if value:
            assert value not in response.text


def test_token_con_espacios_no_se_recorta_y_codigo_con_espacios_es_invalido(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)

    token_response = client.post(
        "/api/autenticacion/activar/manual",
        json={"token": f" {resultado.token} ", "codigo": resultado.codigo},
    )
    codigo_response = client.post(
        "/api/autenticacion/activar/manual",
        json={"token": resultado.token, "codigo": f" {resultado.codigo} "},
    )

    assert token_response.status_code == 404
    assert token_response.json() == {
        "detail": {
            "code": CODIGO_ACTIVACION_NO_DISPONIBLE,
            "message": "Activacion no disponible",
        }
    }
    assert codigo_response.status_code == 422
    assert codigo_response.json() == {"detail": "Solicitud invalida"}
