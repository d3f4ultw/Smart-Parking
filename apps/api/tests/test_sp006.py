from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
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
    DETALLE_ACTIVACION_NO_DISPONIBLE,
    DETALLE_DATOS_ACTIVACION_INVALIDOS,
)
from app.core.database import get_db
from app.esquemas.activaciones import SolicitudActivacionTemporal
from app.models import ActivacionCuenta, Sesion, Usuario
from app.seguridad.contrasenas import (
    ContrasenaInvalidaError,
    verificar_contrasena,
)
from app.servicios.activaciones import (
    ActivacionNoDisponible,
    ResultadoActivacion,
    activar_cuenta_temporal,
    crear_activacion,
)
from app.servicios.autenticacion import autenticar_admin
from app.servicios.usuarios import crear_admin
from main import app


def correo_de_prueba() -> str:
    return f"sp006-test-{uuid4().hex}@example.com"


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


def crear_usuario_manual(db: Session) -> Usuario:
    resultado = crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo_de_prueba(),
        contrasena="Contrasena manual SP006 123",
        confirmacion_contrasena="Contrasena manual SP006 123",
    )
    return resultado.usuario


def crear_activacion_de_prueba(
    db: Session,
    *,
    usuario: Usuario,
    ahora: datetime | None = None,
) -> ResultadoActivacion:
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


def payload_activacion(
    resultado,
    contrasena_temporal: str,
    nueva_contrasena: str = "Nueva contrasena segura SP006",
    confirmar_contrasena: str | None = None,
) -> dict[str, str]:
    return {
        "token": resultado.token,
        "codigo": resultado.codigo,
        "contrasena_temporal": contrasena_temporal,
        "nueva_contrasena": nueva_contrasena,
        "confirmar_contrasena": (
            nueva_contrasena if confirmar_contrasena is None else confirmar_contrasena
        ),
    }


def test_activacion_temporal_cambia_hash_estado_y_no_crea_sesion(
    db: Session,
) -> None:
    ahora = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario, ahora=ahora)
    hash_original = usuario.contrasena_hash
    nueva_contrasena = "Nueva contrasena segura SP006"

    activar_cuenta_temporal(
        db,
        token=resultado.token,
        codigo=resultado.codigo,
        contrasena_temporal=contrasena_temporal,
        nueva_contrasena=nueva_contrasena,
        confirmar_contrasena=nueva_contrasena,
        ahora=ahora,
    )

    db.rollback()
    db.expire_all()
    usuario_persistido = obtener_usuario(db, usuario.id)
    activacion_persistida = obtener_activacion(db, resultado.activacion.id)
    assert usuario_persistido.contrasena_hash is not None
    assert usuario_persistido.contrasena_hash != hash_original
    assert verificar_contrasena(
        nueva_contrasena,
        usuario_persistido.contrasena_hash,
    )
    assert not verificar_contrasena(
        contrasena_temporal,
        usuario_persistido.contrasena_hash,
    )
    assert usuario_persistido.correo_verificado is True
    assert usuario_persistido.debe_cambiar_contrasena is False
    assert activacion_persistida.consumido_en == ahora
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0
    assert contrasena_temporal not in usuario_persistido.contrasena_hash
    assert resultado.token not in activacion_persistida.token_hash
    assert activacion_persistida.codigo_hash is not None
    assert not autenticar_admin(
        db,
        correo=usuario.correo,
        contrasena=contrasena_temporal,
    )
    assert autenticar_admin(
        db,
        correo=usuario.correo,
        contrasena=nueva_contrasena,
    )
    assert resultado.codigo not in activacion_persistida.codigo_hash


def test_endpoint_temporal_devuelve_contrato_minimo_y_no_secretos(
    db: Session,
    client: TestClient,
) -> None:
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    payload = payload_activacion(resultado, contrasena_temporal)

    response = client.post(
        "/api/autenticacion/activar/temporal",
        json=payload,
    )

    assert response.status_code == 200
    assert response.json() == {"estado": "activada"}
    for secreto in payload.values():
        assert secreto not in response.text


def test_token_incorrecto_es_404_generico(db: Session, client: TestClient) -> None:
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    payload = payload_activacion(resultado, contrasena_temporal)
    payload["token"] = f"{resultado.token}-incorrecto"

    response = client.post(
        "/api/autenticacion/activar/temporal",
        json=payload,
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "code": CODIGO_ACTIVACION_NO_DISPONIBLE,
            "message": DETALLE_ACTIVACION_NO_DISPONIBLE,
        }
    }
    for secreto in payload.values():
        assert secreto not in response.text


def test_codigo_incorrecto_es_422_generico(db: Session, client: TestClient) -> None:
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    payload = payload_activacion(resultado, contrasena_temporal)
    payload["codigo"] = str((int(resultado.codigo) + 1) % 1_000_000).zfill(6)

    response = client.post(
        "/api/autenticacion/activar/temporal",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": CODIGO_DATOS_ACTIVACION_INVALIDOS,
            "message": DETALLE_DATOS_ACTIVACION_INVALIDOS,
        }
    }
    for secreto in payload.values():
        assert secreto not in response.text


def test_contrasena_temporal_incorrecta_es_422_generico(
    db: Session,
    client: TestClient,
) -> None:
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    payload = payload_activacion(resultado, contrasena_temporal)
    payload["contrasena_temporal"] = "Contrasena temporal incorrecta"

    response = client.post(
        "/api/autenticacion/activar/temporal",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": CODIGO_DATOS_ACTIVACION_INVALIDOS,
            "message": DETALLE_DATOS_ACTIVACION_INVALIDOS,
        }
    }
    for secreto in payload.values():
        assert secreto not in response.text


def test_activacion_expirada_es_404_generico(
    db: Session,
    client: TestClient,
) -> None:
    inicio = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario, ahora=inicio)
    activacion = obtener_activacion(db, resultado.activacion.id)
    activacion.expira_en = inicio
    db.commit()
    db.rollback()

    response = client.post(
        "/api/autenticacion/activar/temporal",
        json=payload_activacion(resultado, contrasena_temporal),
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "code": CODIGO_ACTIVACION_NO_DISPONIBLE,
            "message": DETALLE_ACTIVACION_NO_DISPONIBLE,
        }
    }


def test_activacion_consumida_es_404_generico(
    db: Session,
    client: TestClient,
) -> None:
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    activacion = obtener_activacion(db, resultado.activacion.id)
    activacion.consumido_en = datetime.now(UTC)
    db.commit()
    db.rollback()

    response = client.post(
        "/api/autenticacion/activar/temporal",
        json=payload_activacion(resultado, contrasena_temporal),
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "code": CODIGO_ACTIVACION_NO_DISPONIBLE,
            "message": DETALLE_ACTIVACION_NO_DISPONIBLE,
        }
    }


@pytest.mark.parametrize("campo", ["esta_activo", "correo_verificado"])
def test_usuario_inactivo_o_verificado_es_404_generico(
    db: Session,
    client: TestClient,
    campo: str,
) -> None:
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    setattr(usuario, campo, False if campo == "esta_activo" else True)
    db.commit()
    db.rollback()

    response = client.post(
        "/api/autenticacion/activar/temporal",
        json=payload_activacion(resultado, contrasena_temporal),
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "code": CODIGO_ACTIVACION_NO_DISPONIBLE,
            "message": DETALLE_ACTIVACION_NO_DISPONIBLE,
        }
    }


def test_usuario_manual_es_rechazado_por_el_flujo_temporal(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    payload = payload_activacion(resultado, "Contrasena manual SP006 123")

    response = client.post(
        "/api/autenticacion/activar/temporal",
        json=payload,
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "code": CODIGO_ACTIVACION_NO_DISPONIBLE,
            "message": DETALLE_ACTIVACION_NO_DISPONIBLE,
        }
    }


def test_nueva_contrasena_de_9_caracteres_es_rechazada(db: Session) -> None:
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)

    with pytest.raises(ContrasenaInvalidaError):
        activar_cuenta_temporal(
            db,
            token=resultado.token,
            codigo=resultado.codigo,
            contrasena_temporal=contrasena_temporal,
            nueva_contrasena="Abcdefghi",
            confirmar_contrasena="Abcdefghi",
        )

    db.rollback()
    assert obtener_usuario(db, usuario.id).debe_cambiar_contrasena is True
    assert obtener_activacion(db, resultado.activacion.id).consumido_en is None


@pytest.mark.parametrize(
    "nueva_contrasena",
    ["Abcdefghij", "X" + "x" * 127],
)
def test_nueva_contrasena_de_10_y_128_caracteres_es_aceptada(
    db: Session,
    nueva_contrasena: str,
) -> None:
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)

    activar_cuenta_temporal(
        db,
        token=resultado.token,
        codigo=resultado.codigo,
        contrasena_temporal=contrasena_temporal,
        nueva_contrasena=nueva_contrasena,
        confirmar_contrasena=nueva_contrasena,
    )

    db.rollback()
    db.expire_all()
    usuario_persistido = obtener_usuario(db, usuario.id)
    assert usuario_persistido.contrasena_hash is not None
    assert verificar_contrasena(
        nueva_contrasena,
        usuario_persistido.contrasena_hash,
    )


@pytest.mark.parametrize("nueva_contrasena", ["Abcdefghi", "abcdefghij"])
def test_endpoint_rechaza_politica_de_contrasena_invalida(
    db: Session,
    client: TestClient,
    nueva_contrasena: str,
) -> None:
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    payload = payload_activacion(
        resultado,
        contrasena_temporal,
        nueva_contrasena=nueva_contrasena,
    )

    response = client.post(
        "/api/autenticacion/activar/temporal",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": CODIGO_DATOS_ACTIVACION_INVALIDOS,
            "message": DETALLE_DATOS_ACTIVACION_INVALIDOS,
        }
    }
    assert nueva_contrasena not in response.text
    db.rollback()
    assert obtener_usuario(db, usuario.id).debe_cambiar_contrasena is True
    assert obtener_activacion(db, resultado.activacion.id).consumido_en is None


def test_nueva_contrasena_de_129_caracteres_es_rechazada(
    db: Session,
    client: TestClient,
) -> None:
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    nueva_contrasena = "x" * 129
    payload = payload_activacion(
        resultado,
        contrasena_temporal,
        nueva_contrasena=nueva_contrasena,
    )

    response = client.post(
        "/api/autenticacion/activar/temporal",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Solicitud invalida"}
    assert nueva_contrasena not in response.text


def test_confirmacion_diferente_es_rechazada_de_forma_segura(
    db: Session,
    client: TestClient,
) -> None:
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    payload = payload_activacion(
        resultado,
        contrasena_temporal,
        confirmar_contrasena="Otra contrasena segura SP006",
    )

    response = client.post(
        "/api/autenticacion/activar/temporal",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": CODIGO_DATOS_ACTIVACION_INVALIDOS,
            "message": DETALLE_DATOS_ACTIVACION_INVALIDOS,
        }
    }
    for secreto in payload.values():
        assert secreto not in response.text


def test_nueva_contrasena_igual_a_temporal_es_rechazada(
    db: Session,
    client: TestClient,
) -> None:
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)
    payload = payload_activacion(
        resultado,
        contrasena_temporal,
        nueva_contrasena=contrasena_temporal,
    )

    response = client.post(
        "/api/autenticacion/activar/temporal",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": CODIGO_DATOS_ACTIVACION_INVALIDOS,
            "message": DETALLE_DATOS_ACTIVACION_INVALIDOS,
        }
    }
    for secreto in payload.values():
        assert secreto not in response.text


def test_doble_consumo_temporal_solo_permite_un_exito(db: Session) -> None:
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario)

    def activar() -> None:
        activar_cuenta_temporal(
            db,
            token=resultado.token,
            codigo=resultado.codigo,
            contrasena_temporal=contrasena_temporal,
            nueva_contrasena="Nueva contrasena segura SP006",
            confirmar_contrasena="Nueva contrasena segura SP006",
        )

    activar()
    db.rollback()

    with pytest.raises(ActivacionNoDisponible):
        activar()

    db.rollback()
    assert (
        db.scalar(
            select(func.count())
            .select_from(ActivacionCuenta)
            .where(ActivacionCuenta.consumido_en.is_not(None))
        )
        == 1
    )


def test_consumo_temporal_concurrente_usa_bloqueo_de_fila(db: Session) -> None:
    usuario, contrasena_temporal = crear_usuario_temporal(db)
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
            activar_cuenta_temporal(
                sesion,
                token=resultado.token,
                codigo=resultado.codigo,
                contrasena_temporal=contrasena_temporal,
                nueva_contrasena="Nueva contrasena segura SP006",
                confirmar_contrasena="Nueva contrasena segura SP006",
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
    assert obtener_usuario(db, usuario.id).debe_cambiar_contrasena is False
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0


def test_fallo_de_base_de_datos_hace_rollback_completo(db: Session) -> None:
    ahora = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    usuario, contrasena_temporal = crear_usuario_temporal(db)
    resultado = crear_activacion_de_prueba(db, usuario=usuario, ahora=ahora)
    hash_original = usuario.contrasena_hash

    with patch.object(db, "flush", side_effect=SQLAlchemyError("fallo controlado")):
        with pytest.raises(SQLAlchemyError):
            activar_cuenta_temporal(
                db,
                token=resultado.token,
                codigo=resultado.codigo,
                contrasena_temporal=contrasena_temporal,
                nueva_contrasena="Nueva contrasena segura SP006",
                confirmar_contrasena="Nueva contrasena segura SP006",
                ahora=ahora,
            )

    db.rollback()
    db.expire_all()
    usuario_persistido = obtener_usuario(db, usuario.id)
    activacion_persistida = obtener_activacion(db, resultado.activacion.id)
    assert usuario_persistido.contrasena_hash == hash_original
    assert usuario_persistido.correo_verificado is False
    assert usuario_persistido.debe_cambiar_contrasena is True
    assert activacion_persistida.consumido_en is None


def test_payload_invalido_no_refleja_secretos(
    client: TestClient,
) -> None:
    payload = {
        "token": "token-secreto",
        "codigo": "12345",
        "contrasena_temporal": "temporal-secreta",
        "nueva_contrasena": "nueva-secreta",
        "confirmar_contrasena": "nueva-secreta",
    }

    response = client.post(
        "/api/autenticacion/activar/temporal",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Solicitud invalida"}
    modelo_valido = payload | {"codigo": "123456"}
    assert repr(SolicitudActivacionTemporal(**modelo_valido)) == (
        "SolicitudActivacionTemporal()"
    )
    for secreto in payload.values():
        assert secreto not in response.text
