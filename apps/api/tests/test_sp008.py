from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.api.rutas.activaciones import ESTADO_REENVIO_ACTIVACION
from app.core.config import Settings
from app.core.database import get_db
from app.models import ActivacionCuenta, RolUsuario, Sesion, Usuario
from app.seguridad.activaciones import (
    hash_codigo_verificacion,
    hash_token_activacion,
)
from app.seguridad.contrasenas import verificar_contrasena
from app.servicios.activaciones import (
    ActivacionNoDisponible,
    CooldownReenvioError,
    ErrorReenvioActivacion,
    activar_cuenta_temporal,
    crear_activacion,
    reenviar_activacion,
)
from app.servicios.usuarios import crear_admin
from main import app

RUTA_REENVIO = "/api/autenticacion/activacion/reenviar"


def correo_de_prueba() -> str:
    return f"sp008-test-{uuid4().hex}@example.com"


def settings_de_prueba(*, cooldown_segundos: int = 60) -> Settings:
    return Settings(
        database_host="localhost",
        database_port=5432,
        database_name="unused",
        database_user="unused",
        database_password=SecretStr("test-db-password"),
        activation_token_ttl_hours=24,
        activation_challenge_ttl_minutes=15,
        smtp_from_email="no-reply@example.com",
        app_public_url="https://parking.example",
        activacion_reenvio_cooldown_segundos=cooldown_segundos,
    )


def cooldown_de_prueba(cooldown_segundos: int = 60) -> int:
    return settings_de_prueba(
        cooldown_segundos=cooldown_segundos,
    ).activacion_reenvio_cooldown_segundos


def crear_usuario_manual(db: Session, correo: str | None = None) -> Usuario:
    resultado = crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo or correo_de_prueba(),
        contrasena="Contrasena manual SP008 123",
        confirmacion_contrasena="Contrasena manual SP008 123",
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


def crear_activacion_controlada(
    db: Session,
    usuario: Usuario,
    *,
    ahora: datetime,
):
    resultado = crear_activacion(db, usuario.id, ahora=ahora)
    resultado.activacion.creado_en = ahora
    db.commit()
    db.rollback()
    return resultado


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


def test_reenvio_manual_conserva_hash_invalida_anterior_y_expira_en_15_minutos(
    db: Session,
) -> None:
    inicio = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    cooldown = cooldown_de_prueba()
    usuario = crear_usuario_manual(db)
    primera = crear_activacion_controlada(db, usuario, ahora=inicio)
    hash_original = usuario.contrasena_hash
    momento_reenvio = inicio + timedelta(seconds=cooldown)

    resultado = reenviar_activacion(
        db,
        usuario.correo,
        cooldown_segundos=cooldown,
        ahora=momento_reenvio,
    )

    assert resultado is not None
    assert resultado.contrasena_temporal is None
    assert resultado.activacion.id != primera.activacion.id
    assert resultado.activacion.expira_en - momento_reenvio == timedelta(minutes=15)
    assert resultado.activacion.token_hash == hash_token_activacion(resultado.token)
    assert resultado.activacion.codigo_hash != hash_codigo_verificacion("000000")

    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    primera_persistida = db.get(ActivacionCuenta, primera.activacion.id)
    segunda_persistida = db.get(ActivacionCuenta, resultado.activacion.id)
    assert usuario_persistido is not None
    assert primera_persistida is not None
    assert segunda_persistida is not None
    assert usuario_persistido.contrasena_hash == hash_original
    assert primera_persistida.consumido_en == momento_reenvio
    assert segunda_persistida.consumido_en is None
    assert segunda_persistida.codigo_hash is not None
    assert verificar_contrasena(resultado.codigo, segunda_persistida.codigo_hash)
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0


def test_reenvio_rechaza_operador_y_conserva_activacion_pendiente(
    db: Session,
) -> None:
    inicio = datetime(2026, 9, 27, 12, 30, tzinfo=UTC)
    usuario = crear_usuario_manual(db)
    primera = crear_activacion_controlada(db, usuario, ahora=inicio)
    usuario.rol = RolUsuario.OPERADOR.value
    db.commit()
    db.rollback()

    resultado = reenviar_activacion(
        db,
        usuario.correo,
        cooldown_segundos=cooldown_de_prueba(),
        ahora=inicio + timedelta(minutes=2),
    )

    assert resultado is None
    db.rollback()
    activaciones = list(
        db.scalars(
            select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == usuario.id)
        ).all()
    )
    assert len(activaciones) == 1
    assert activaciones[0].id == primera.activacion.id
    assert activaciones[0].consumido_en is None
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0


def test_reenvio_temporal_reemplaza_hash_y_la_nueva_temporal_puede_activar(
    db: Session,
) -> None:
    inicio = datetime(2026, 9, 27, 13, 0, tzinfo=UTC)
    cooldown = cooldown_de_prueba()
    usuario, contrasena_anterior = crear_usuario_temporal(db)
    primera = crear_activacion_controlada(db, usuario, ahora=inicio)
    hash_anterior = usuario.contrasena_hash

    resultado = reenviar_activacion(
        db,
        usuario.correo,
        cooldown_segundos=cooldown,
        ahora=inicio + timedelta(seconds=cooldown + 1),
    )

    assert resultado is not None
    assert resultado.contrasena_temporal is not None
    assert resultado.contrasena_temporal != contrasena_anterior
    assert resultado.activacion.id != primera.activacion.id

    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    primera_persistida = db.get(ActivacionCuenta, primera.activacion.id)
    assert usuario_persistido is not None
    assert primera_persistida is not None
    assert usuario_persistido.contrasena_hash is not None
    assert usuario_persistido.contrasena_hash != hash_anterior
    assert not verificar_contrasena(
        contrasena_anterior,
        usuario_persistido.contrasena_hash,
    )
    assert verificar_contrasena(
        resultado.contrasena_temporal,
        usuario_persistido.contrasena_hash,
    )
    assert primera_persistida.consumido_en is not None

    with pytest.raises(ActivacionNoDisponible):
        activar_cuenta_temporal(
            db,
            token=primera.token,
            codigo=primera.codigo,
            contrasena_temporal=contrasena_anterior,
            nueva_contrasena="Contrasena definitiva SP008 123",
            confirmar_contrasena="Contrasena definitiva SP008 123",
        )

    db.rollback()
    activar_cuenta_temporal(
        db,
        token=resultado.token,
        codigo=resultado.codigo,
        contrasena_temporal=resultado.contrasena_temporal,
        nueva_contrasena="Contrasena definitiva SP008 123",
        confirmar_contrasena="Contrasena definitiva SP008 123",
        ahora=inicio + timedelta(seconds=cooldown + 1),
    )
    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    assert usuario_persistido is not None
    assert usuario_persistido.correo_verificado is True
    assert usuario_persistido.debe_cambiar_contrasena is False
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0


def test_cooldown_no_genera_credenciales_ni_cambia_estado(db: Session) -> None:
    inicio = datetime(2026, 9, 27, 14, 0, tzinfo=UTC)
    cooldown = cooldown_de_prueba()
    usuario = crear_usuario_manual(db)
    primera = reenviar_activacion(
        db,
        usuario.correo,
        cooldown_segundos=cooldown,
        ahora=inicio,
    )
    assert primera is not None
    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    assert usuario_persistido is not None
    hash_original = usuario_persistido.contrasena_hash

    with (
        patch("app.servicios.activaciones.generar_token_activacion") as token,
        patch("app.servicios.activaciones.generar_codigo_verificacion") as codigo,
        patch("app.servicios.activaciones.generar_contrasena_temporal") as temporal,
        patch("app.servicios.activaciones.crear_hash_contrasena") as hash_password,
    ):
        with pytest.raises(CooldownReenvioError) as error:
            reenviar_activacion(
                db,
                usuario.correo,
                cooldown_segundos=cooldown,
                ahora=inicio + timedelta(seconds=cooldown - 1),
            )

    assert 1 <= error.value.segundos_restantes <= cooldown
    token.assert_not_called()
    codigo.assert_not_called()
    temporal.assert_not_called()
    hash_password.assert_not_called()
    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    assert usuario_persistido is not None
    assert usuario_persistido.contrasena_hash == hash_original
    assert db.scalar(select(func.count()).select_from(ActivacionCuenta)) == 1


def test_cooldown_termina_exactamente_a_los_60_segundos(db: Session) -> None:
    inicio = datetime(2026, 9, 27, 15, 0, tzinfo=UTC)
    cooldown = cooldown_de_prueba()
    usuario = crear_usuario_manual(db)
    primera = reenviar_activacion(
        db,
        usuario.correo,
        cooldown_segundos=cooldown,
        ahora=inicio,
    )
    assert primera is not None
    db.rollback()

    segunda = reenviar_activacion(
        db,
        usuario.correo,
        cooldown_segundos=cooldown,
        ahora=inicio + timedelta(seconds=cooldown),
    )

    assert segunda is not None
    db.rollback()
    assert db.scalar(select(func.count()).select_from(ActivacionCuenta)) == 2


def test_cooldown_configurable_expone_segundos_y_termina_en_el_limite(
    db: Session,
) -> None:
    inicio = datetime(2026, 9, 27, 16, 0, tzinfo=UTC)
    cooldown = cooldown_de_prueba(10)
    usuario = crear_usuario_manual(db)
    correo = usuario.correo
    primera = reenviar_activacion(
        db,
        correo,
        cooldown_segundos=cooldown,
        ahora=inicio,
    )
    assert primera is not None
    db.rollback()

    with pytest.raises(CooldownReenvioError) as error:
        reenviar_activacion(
            db,
            correo,
            cooldown_segundos=cooldown,
            ahora=inicio + timedelta(seconds=4),
        )
    assert error.value.segundos_restantes == 6
    db.rollback()

    with pytest.raises(CooldownReenvioError) as error:
        reenviar_activacion(
            db,
            correo,
            cooldown_segundos=cooldown,
            ahora=inicio + timedelta(seconds=9, milliseconds=200),
        )
    assert error.value.segundos_restantes == 1

    tercera = reenviar_activacion(
        db,
        correo,
        cooldown_segundos=cooldown,
        ahora=inicio + timedelta(seconds=cooldown),
    )
    assert tercera is not None
    db.rollback()
    assert db.scalar(select(func.count()).select_from(ActivacionCuenta)) == 2


@pytest.mark.parametrize("estado", ["desconocido", "verificado", "inactivo"])
def test_casos_no_elegibles_comparten_respuesta_202_y_no_envian_correo(
    db: Session,
    client: TestClient,
    estado: str,
) -> None:
    if estado == "desconocido":
        correo = correo_de_prueba()
    else:
        usuario = crear_usuario_manual(db)
        correo = usuario.correo
        if estado == "verificado":
            usuario.correo_verificado = True
        else:
            usuario.esta_activo = False
        db.commit()
        db.rollback()

    response = client.post(RUTA_REENVIO, json={"correo": correo})

    assert response.status_code == 202
    assert response.json() == {"estado": ESTADO_REENVIO_ACTIVACION}
    assert response.headers["cache-control"] == "no-store"


def test_endpoint_cooldown_conserva_202_generico(
    db: Session,
    client: TestClient,
) -> None:
    ahora = datetime.now(UTC)
    cooldown = cooldown_de_prueba()
    usuario = crear_usuario_manual(db)
    primera = reenviar_activacion(
        db,
        usuario.correo,
        cooldown_segundos=cooldown,
        ahora=ahora,
    )
    assert primera is not None
    db.rollback()

    response = client.post(RUTA_REENVIO, json={"correo": usuario.correo})

    assert response.status_code == 202
    assert response.json() == {"estado": ESTADO_REENVIO_ACTIVACION}
    assert "segundos" not in response.text


def test_endpoint_publico_no_emite_nuevas_invitaciones_legacy(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_manual(db)
    resultado = crear_activacion_controlada(db, usuario, ahora=datetime.now(UTC))
    activacion = resultado.activacion
    hash_anterior = activacion.token_hash
    db.rollback()

    response = client.post(RUTA_REENVIO, json={"correo": usuario.correo})

    assert response.status_code == 202
    assert response.json() == {"estado": ESTADO_REENVIO_ACTIVACION}
    db.rollback()
    actual = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.id == activacion.id)
    )
    assert actual is not None
    assert actual.token_hash == hash_anterior
    assert actual.consumido_en is None


def test_endpoint_publico_no_reemplaza_una_invitacion_existente(
    db: Session,
    client: TestClient,
) -> None:
    correo = correo_de_prueba()
    usuario = crear_usuario_manual(db, correo)
    db.rollback()
    resultado = crear_activacion_controlada(db, usuario, ahora=datetime.now(UTC))
    activacion = resultado.activacion
    db.rollback()
    response = client.post(
        RUTA_REENVIO,
        json={"correo": f"  {correo.upper()}  "},
    )

    assert response.status_code == 202
    assert response.json() == {"estado": ESTADO_REENVIO_ACTIVACION}
    assert correo not in response.text
    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    assert usuario_persistido is not None
    assert usuario_persistido.correo_verificado is False
    assert db.scalar(select(func.count()).select_from(ActivacionCuenta)) == 1
    actual = db.get(ActivacionCuenta, activacion.id)
    assert actual is not None
    assert actual.token_hash == activacion.token_hash


def test_endpoint_publico_no_cambia_password_legacy_temporal(
    db: Session,
    client: TestClient,
) -> None:
    usuario, _contrasena_temporal = crear_usuario_temporal(db)
    db.rollback()
    hash_anterior = usuario.contrasena_hash
    response = client.post(RUTA_REENVIO, json={"correo": usuario.correo})

    assert response.status_code == 202
    assert response.json() == {"estado": ESTADO_REENVIO_ACTIVACION}
    db.rollback()
    usuario_actual = db.get(Usuario, usuario.id)
    assert usuario_actual is not None
    assert usuario_actual.contrasena_hash == hash_anterior
    assert db.scalar(select(func.count()).select_from(ActivacionCuenta)) == 0


def test_correo_invalido_es_422_generico(client: TestClient) -> None:
    response = client.post(RUTA_REENVIO, json={"correo": "no-es-un-correo"})

    assert response.status_code == 422
    assert response.json() == {"detail": "Solicitud invalida"}
    assert "no-es-un-correo" not in response.text


def test_rollback_no_deja_invalida_la_activacion_anterior(db: Session) -> None:
    inicio = datetime(2026, 9, 27, 16, 0, tzinfo=UTC)
    cooldown = cooldown_de_prueba()
    usuario = crear_usuario_manual(db)
    primera = crear_activacion_controlada(db, usuario, ahora=inicio)
    hash_original = usuario.contrasena_hash
    db.rollback()

    with patch.object(
        db,
        "flush",
        side_effect=SQLAlchemyError("fallo controlado de SP008"),
    ):
        with pytest.raises(ErrorReenvioActivacion):
            reenviar_activacion(
                db,
                usuario.correo,
                cooldown_segundos=cooldown,
                ahora=inicio + timedelta(seconds=cooldown + 1),
            )

    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    activacion_persistida = db.get(ActivacionCuenta, primera.activacion.id)
    assert usuario_persistido is not None
    assert activacion_persistida is not None
    assert usuario_persistido.contrasena_hash == hash_original
    assert activacion_persistida.consumido_en is None
    assert db.scalar(select(func.count()).select_from(ActivacionCuenta)) == 1


def test_endpoint_publico_no_toca_datos_legacy_ni_intenta_smtp(
    db: Session,
    client: TestClient,
) -> None:
    usuario = crear_usuario_manual(db)
    db.rollback()
    response = client.post(RUTA_REENVIO, json={"correo": usuario.correo})

    assert response.status_code == 202
    assert response.json() == {"estado": ESTADO_REENVIO_ACTIVACION}
    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    assert usuario_persistido is not None
    assert usuario_persistido.correo_verificado is False
    assert db.scalar(select(func.count()).select_from(ActivacionCuenta)) == 0
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0


def test_dos_reenvios_concurrentes_solo_crean_una_activacion(db: Session) -> None:
    ahora = datetime(2026, 9, 27, 17, 0, tzinfo=UTC)
    cooldown = cooldown_de_prueba()
    usuario = crear_usuario_manual(db)
    correo = usuario.correo
    db.rollback()
    engine = db.get_bind()
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    barrera = Barrier(2)

    def intentar_reenvio() -> bool:
        sesion = session_factory()
        try:
            barrera.wait()
            try:
                return (
                    reenviar_activacion(
                        sesion,
                        correo,
                        cooldown_segundos=cooldown,
                        ahora=ahora,
                    )
                    is not None
                )
            except CooldownReenvioError:
                return False
        finally:
            sesion.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        resultados = list(executor.map(lambda _indice: intentar_reenvio(), range(2)))

    db.rollback()
    assert sorted(resultados) == [False, True]
    assert db.scalar(select(func.count()).select_from(ActivacionCuenta)) == 1
    assert (
        db.scalar(
            select(func.count())
            .select_from(ActivacionCuenta)
            .where(ActivacionCuenta.consumido_en.is_(None))
        )
        == 1
    )
