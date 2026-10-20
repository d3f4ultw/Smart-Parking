from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

import app.servicios.cuentas_clientes as servicios_cuentas_clientes
import main
from app.core.database import get_db
from app.esquemas.cuentas_clientes import SolicitudRegistroCliente
from app.models import (
    Cliente,
    CuentaCliente,
    EventoTiempoReal,
    FacturaMembresia,
    Membresia,
    Sesion,
    Usuario,
)
from app.servicios.cuentas_clientes import registrar_cuenta_cliente


def _datos_registro(correo_base: str, **cambios: object) -> dict[str, object]:
    datos: dict[str, object] = {
        "nombre": "  María  ",
        "apellido_paterno": " López ",
        "correo": correo_base,
        "contrasena": "Password1!",
    }
    datos.update(cambios)
    return datos


@pytest.fixture
def client(
    database_url: URL,
) -> Generator[TestClient]:
    motor = create_engine(database_url, pool_pre_ping=True)

    def entregar_db() -> Generator[Session]:
        with Session(motor, autoflush=False, expire_on_commit=False) as sesion:
            yield sesion

    main.app.dependency_overrides[get_db] = entregar_db
    try:
        with TestClient(main.app) as test_client:
            yield test_client
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        motor.dispose()


def test_registro_crea_hash_argon2id_y_no_crea_sesion_personal_ni_stripe(
    client: TestClient,
    db: Session,
) -> None:
    correo = f"cliente-{uuid4().hex}@example.com"
    contrasena = "Password1!"

    respuesta = client.post(
        "/api/clientes/registro",
        json=_datos_registro(correo, apellido_materno="  García  "),
    )

    assert respuesta.status_code == 202
    assert respuesta.json() == {"estado": "solicitud_recibida"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert "set-cookie" not in respuesta.headers
    assert contrasena not in respuesta.text
    db.expire_all()
    cuenta = db.scalar(
        select(CuentaCliente).where(CuentaCliente.correo == correo.casefold())
    )
    assert cuenta is not None
    assert cuenta.nombre == "María"
    assert cuenta.apellido_paterno == "López"
    assert cuenta.apellido_materno == "García"
    assert cuenta.correo_verificado is False
    assert cuenta.esta_activa is True
    assert cuenta.contrasena_hash.startswith("$argon2id$")
    assert PasswordHasher().verify(cuenta.contrasena_hash, contrasena)
    assert cuenta.contrasena_hash != contrasena
    assert db.scalar(select(func.count()).select_from(Usuario)) == 0
    assert db.scalar(select(func.count()).select_from(Sesion)) == 0
    cliente = db.scalar(
        select(Cliente).where(Cliente.cuenta_cliente_id == cuenta.id)
    )
    assert cliente is not None
    assert cliente.stripe_customer_id is None
    assert cliente.correo_privado is None
    assert cliente.nombre_completo == "María López García"
    assert db.scalar(select(func.count()).select_from(Cliente)) == 1
    evento = db.scalar(
        select(EventoTiempoReal).where(EventoTiempoReal.tipo == "cliente.registrado")
    )
    assert evento is not None
    assert evento.recurso_tipo == "cliente"
    assert evento.recurso_id == cliente.id
    assert evento.datos is None
    assert db.scalar(select(func.count()).select_from(Membresia)) == 0
    assert db.scalar(select(func.count()).select_from(FacturaMembresia)) == 0


def test_apellido_materno_opcional_y_correo_duplicado_usan_la_misma_respuesta(
    client: TestClient,
    db: Session,
) -> None:
    correo = f"Caso-{uuid4().hex}@Example.com"
    primera = client.post("/api/clientes/registro", json=_datos_registro(correo))
    segunda = client.post(
        "/api/clientes/registro",
        json=_datos_registro(correo.upper(), apellido_materno=""),
    )

    assert primera.status_code == segunda.status_code == 202
    assert primera.content == segunda.content
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(CuentaCliente)) == 1
    assert db.scalar(select(func.count()).select_from(Cliente)) == 1
    assert db.scalar(
        select(func.count())
        .select_from(EventoTiempoReal)
        .where(EventoTiempoReal.tipo == "cliente.registrado")
    ) == 1
    cuenta = db.scalar(
        select(CuentaCliente).where(CuentaCliente.correo == correo.casefold())
    )
    assert cuenta is not None
    assert cuenta.apellido_materno is None


def test_correo_de_personal_y_cliente_permanecen_en_identidades_separadas(
    client: TestClient,
    db: Session,
) -> None:
    correo = f"identidad-separada-{uuid4().hex}@example.com"
    usuario = Usuario(
        nombre="Personal",
        apellido_paterno="Sintético",
        correo=correo,
        contrasena_hash="hash-no-autenticable-de-prueba",
        rol="OWNER",
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(usuario)
    db.commit()

    respuesta = client.post(
        "/api/clientes/registro",
        json=_datos_registro(correo.upper()),
    )

    assert respuesta.status_code == 202
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Usuario)) == 1
    assert db.scalar(select(func.count()).select_from(CuentaCliente)) == 1
    usuario_persistido = db.scalar(select(Usuario).where(Usuario.correo == correo))
    assert usuario_persistido is not None
    assert usuario_persistido.rol == "OWNER"


def test_registro_exige_nombre_apellido_correo_y_contrasena(
    client: TestClient,
) -> None:
    datos = _datos_registro(f"requerido-{uuid4().hex}@example.com")
    for campo in ("nombre", "apellido_paterno", "correo", "contrasena"):
        solicitud = dict(datos)
        solicitud.pop(campo)
        respuesta = client.post("/api/clientes/registro", json=solicitud)
        assert respuesta.status_code == 422
        assert respuesta.json() == {"detail": "Solicitud invalida"}


def test_solicitud_no_incluye_correo_ni_contrasena_en_repr() -> None:
    correo = "privado@example.com"
    contrasena = "Password1!"
    solicitud = SolicitudRegistroCliente.model_validate(
        _datos_registro(correo, contrasena=contrasena)
    )

    assert correo not in repr(solicitud)
    assert contrasena not in repr(solicitud)


@pytest.mark.parametrize(
    "cambios",
    [
        {"nombre": "  "},
        {"apellido_paterno": "  "},
        {"correo": "no-es-correo"},
        {"contrasena": "short"},
        {"contrasena": "minusculas123!"},
        {"rol": "OWNER"},
        {"esta_activa": False},
        {"stripe_customer_id": "cus_synthetic"},
    ],
)
def test_registro_rechaza_campos_invalidos_o_privilegiados(
    client: TestClient,
    db: Session,
    cambios: dict[str, object],
) -> None:
    respuesta = client.post(
        "/api/clientes/registro",
        json=_datos_registro(f"invalido-{uuid4().hex}@example.com", **cambios),
    )

    assert respuesta.status_code == 422
    assert respuesta.json() == {"detail": "Solicitud invalida"}
    assert "Password1!" not in respuesta.text
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(CuentaCliente)) == 0


def test_registro_rechaza_tipo_de_contenido_y_cuerpo_mayor_a_8_kib(
    client: TestClient,
) -> None:
    tipo_invalido = client.post(
        "/api/clientes/registro",
        content=b"{}",
        headers={"content-type": "text/plain"},
    )
    cuerpo_grande = client.post(
        "/api/clientes/registro",
        content=b"{" + b" " * (8 * 1024) + b"}",
        headers={"content-type": "application/json"},
    )

    assert tipo_invalido.status_code == 415
    assert tipo_invalido.headers["cache-control"] == "no-store"
    assert cuerpo_grande.status_code == 413
    assert cuerpo_grande.headers["cache-control"] == "no-store"


def test_registro_aplica_limite_por_correo_y_no_expone_cuenta_duplicada(
    client: TestClient,
    db: Session,
) -> None:
    correo = f"limitado-{uuid4().hex}@example.com"
    respuestas = [
        client.post("/api/clientes/registro", json=_datos_registro(correo))
        for _ in range(6)
    ]

    assert [respuesta.status_code for respuesta in respuestas] == [
        202,
        202,
        202,
        202,
        202,
        429,
    ]
    assert all(
        respuesta.content == respuestas[0].content for respuesta in respuestas[:5]
    )
    assert respuestas[-1].headers["cache-control"] == "no-store"
    assert correo not in "".join(respuesta.text for respuesta in respuestas)
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(CuentaCliente)) == 1


def test_correo_repetido_concurrentemente_se_resuelve_por_indice_postgresql(
    database_url: URL,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    motor = create_engine(database_url, pool_pre_ping=True)
    barrera = Barrier(2)
    monkeypatch.setattr(
        servicios_cuentas_clientes,
        "crear_hash_contrasena",
        lambda _contrasena: (barrera.wait(timeout=10), "$argon2id$race-test")[1],
    )
    correo = f"concurrente-{uuid4().hex}@example.com"

    def intentar_registro() -> bool:
        with Session(motor, autoflush=False, expire_on_commit=False) as sesion:
            return registrar_cuenta_cliente(
                sesion,
                nombre="Cuenta",
                apellido_paterno="Concurrente",
                apellido_materno=None,
                correo=correo,
                contrasena="Password1!",
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            resultados = list(
                ejecutor.map(lambda _indice: intentar_registro(), range(2))
            )
        assert sorted(resultados) == [False, True]
        with Session(motor) as sesion:
            assert sesion.scalar(select(func.count()).select_from(CuentaCliente)) == 1
        db.expire_all()
        assert db.scalar(select(func.count()).select_from(CuentaCliente)) == 1
    finally:
        motor.dispose()


def test_migracion_no_permite_retirar_cuentas_registradas(
    database_url: URL,
    db: Session,
) -> None:
    registrar_cuenta_cliente(
        db,
        nombre="Cuenta",
        apellido_paterno="Protegida",
        apellido_materno=None,
        correo=f"protegida-{uuid4().hex}@example.com",
        contrasena="Password1!",
    )
    raiz_api = Path(__file__).resolve().parents[1]
    resultado = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "20261019_0002"],
        cwd=raiz_api,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert resultado.returncode != 0
    assert "Hay datos de clientes que requieren esta migracion" in (
        resultado.stdout + resultado.stderr
    )
    motor = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(motor) as sesion:
            version = sesion.scalar(text("SELECT version_num FROM alembic_version"))
            assert version == "20261020_0003"
    finally:
        motor.dispose()
