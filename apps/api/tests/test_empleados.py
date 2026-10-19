from __future__ import annotations

import secrets
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import TypedDict
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

import app.api.dependencias as dependencias
import app.api.rutas.eventos as rutas_eventos
import main
from app.api.rutas.empleados import formatear_codigo_empleado
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models import Empleado, RolUsuario, Sesion, TurnoEmpleado, Usuario
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.configuracion_estacionamiento import (
    cambiar_modalidad_estacionamiento,
)
from app.servicios.empleados import (
    cambiar_estado_empleado,
    registrar_empleado,
)

NOMBRE_COOKIE_SESION = get_settings().session_cookie_name
RUTA_EMPLEADOS = "/api/admin/empleados"


class TurnoRespuesta(TypedDict):
    id: str


class EmpleadoRespuesta(TypedDict):
    id: str
    codigo_empleado: str
    nombres: str
    apellido_paterno: str
    apellido_materno: str | None
    turno: TurnoRespuesta
    esta_activo: bool
    revision_estado: int


def _crear_settings() -> Settings:
    return Settings.model_validate(
        {
            "database_host": "localhost",
            "database_port": 5432,
            "database_name": "smart_parking_test",
            "database_user": "smart_parking_test",
            "database_password": SecretStr("database-secret-test-only"),
            "activation_token_ttl_hours": 24,
            "activation_challenge_ttl_minutes": 15,
            "correo_transporte": "smtp",
            "smtp_host": "mailpit",
            "smtp_port": "1025",
            "smtp_from_email": "no-reply@example.test",
            "smtp_security": "none",
        }
    )


@pytest.fixture
def client(
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient]:
    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    settings = _crear_settings()

    def entregar_db() -> Generator[Session]:
        sesion = fabrica()
        try:
            yield sesion
        finally:
            sesion.close()

    main.app.dependency_overrides[get_db] = entregar_db
    monkeypatch.setattr(dependencias, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(rutas_eventos, "SessionLocal", fabrica)
    try:
        with TestClient(main.app) as test_client:
            yield test_client
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        motor.dispose()


def _crear_usuario(db: Session, rol: str) -> int:
    usuario = Usuario(
        nombre="Prueba",
        apellido_paterno="Empleados",
        apellido_materno="Sintetico",
        correo=f"empleados-{uuid4().hex}@example.invalid",
        contrasena_hash="hash-sintetico-empleados",
        rol=rol,
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(usuario)
    db.flush()
    usuario_id = usuario.id
    db.commit()
    db.rollback()
    return usuario_id


def _crear_sesion(db: Session, usuario_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        Sesion(
            usuario_id=usuario_id,
            token_hash=hash_token_sesion(token),
            expira_en=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db.commit()
    db.rollback()
    return token


def _usar_sesion(client: TestClient, token: str | None) -> None:
    if token is None:
        client.cookies.delete(NOMBRE_COOKIE_SESION)
    else:
        client.cookies.set(NOMBRE_COOKIE_SESION, token)


def _habilitar_modalidad(db: Session, modalidad: str = "MIXTO") -> None:
    configuracion = cambiar_modalidad_estacionamiento(
        db,
        modalidad,
        revision_esperada=0,
    )
    assert configuracion.configuracion is not None
    db.rollback()


def _crear_empleado(
    client: TestClient,
    turno_id: str,
    *,
    clave: str | None = None,
    nombres: str = "Andrea",
) -> tuple[str, EmpleadoRespuesta]:
    clave_solicitud = clave or str(uuid4())
    respuesta = client.post(
        RUTA_EMPLEADOS,
        headers={"Idempotency-Key": clave_solicitud},
        json={
            "nombres": nombres,
            "apellido_paterno": "Pruebas",
            "turno_empleado_id": int(turno_id),
        },
    )
    assert respuesta.status_code == 201
    return clave_solicitud, respuesta.json()


def _turno_id(client: TestClient) -> str:
    respuesta = client.get(RUTA_EMPLEADOS)
    assert respuesta.status_code == 200
    return respuesta.json()["turnos_disponibles"][0]["id"]


@pytest.mark.parametrize(
    ("empleado_id", "codigo_esperado"),
    (
        (1, "E-0001"),
        (25, "E-0025"),
        (9999, "E-9999"),
        (10000, "E-10000"),
    ),
)
def test_formatea_codigo_empleado_desde_el_id_numerico(
    empleado_id: int,
    codigo_esperado: str,
) -> None:
    assert formatear_codigo_empleado(empleado_id) == codigo_esperado


def test_solo_owner_puede_listar_registrar_y_cambiar_estado(
    client: TestClient,
    db: Session,
) -> None:
    _habilitar_modalidad(db)
    owner_id = _crear_usuario(db, RolUsuario.OWNER.value)
    operador_id = _crear_usuario(db, RolUsuario.OPERADOR.value)
    token_owner = _crear_sesion(db, owner_id)
    token_operador = _crear_sesion(db, operador_id)

    sin_sesion = client.get(RUTA_EMPLEADOS)
    assert sin_sesion.status_code == 401
    assert sin_sesion.headers["cache-control"] == "no-store"

    _usar_sesion(client, token_owner)
    listado = client.get(RUTA_EMPLEADOS)
    assert listado.status_code == 200
    assert listado.headers["cache-control"] == "no-store"
    assert [turno["nombre"] for turno in listado.json()["turnos_disponibles"]] == [
        "Matutino",
        "Vespertino",
        "Nocturno",
        "Sin restricción",
    ]
    assert all(
        "hora_inicio" not in turno and "hora_fin" not in turno
        for turno in listado.json()["turnos_disponibles"]
    )
    clave, empleado = _crear_empleado(client, _turno_id(client))

    _usar_sesion(client, token_operador)
    operaciones = (
        client.get(RUTA_EMPLEADOS),
        client.post(
            RUTA_EMPLEADOS,
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "nombres": "Operador",
                "apellido_paterno": "Denegado",
                "turno_empleado_id": int(empleado["turno"]["id"]),
            },
        ),
        client.patch(
            f"{RUTA_EMPLEADOS}/{empleado['id']}/estado",
            json={"esta_activo": False, "revision_esperada": 1},
        ),
    )
    assert [respuesta.status_code for respuesta in operaciones] == [403, 403, 403]
    assert all(
        respuesta.headers["cache-control"] == "no-store" for respuesta in operaciones
    )
    assert db.scalar(select(func.count()).select_from(Empleado)) == 1
    assert clave


def test_registro_valida_campos_turno_y_reintentos_idempotentes(
    client: TestClient,
    db: Session,
) -> None:
    _habilitar_modalidad(db)
    usuario_id = _crear_usuario(db, RolUsuario.OWNER.value)
    _usar_sesion(client, _crear_sesion(db, usuario_id))
    turno_id = _turno_id(client)
    clave = str(uuid4())
    solicitud = {
        "nombres": "  Ana María  ",
        "apellido_paterno": " López ",
        "apellido_materno": "   ",
        "turno_empleado_id": int(turno_id),
    }

    creado = client.post(
        RUTA_EMPLEADOS,
        headers={"Idempotency-Key": clave},
        json=solicitud,
    )
    assert creado.status_code == 201
    assert creado.headers["cache-control"] == "no-store"
    empleado = creado.json()
    assert empleado["id"].isdigit()
    assert empleado["codigo_empleado"] == formatear_codigo_empleado(
        int(empleado["id"])
    )
    assert empleado["nombres"] == "Ana María"
    assert empleado["apellido_paterno"] == "López"
    assert empleado["apellido_materno"] is None
    assert empleado["esta_activo"] is True
    assert empleado["revision_estado"] == 1
    assert empleado["turno"] == {
        "id": turno_id,
        "codigo": "MATUTINO",
        "nombre": "Matutino",
    }
    assert "clave_solicitud" not in empleado
    assert "hora_inicio" not in empleado["turno"]

    repetido = client.post(
        RUTA_EMPLEADOS,
        headers={"Idempotency-Key": clave},
        json=solicitud,
    )
    assert repetido.status_code == 200
    assert repetido.json() == empleado

    conflicto = client.post(
        RUTA_EMPLEADOS,
        headers={"Idempotency-Key": clave},
        json={**solicitud, "nombres": "Otro nombre"},
    )
    assert conflicto.status_code == 409
    assert (
        client.post(
            RUTA_EMPLEADOS,
            headers={"Idempotency-Key": str(uuid4())},
            json=solicitud,
        ).json()["id"]
        != empleado["id"]
    )
    assert db.scalar(select(func.count()).select_from(Empleado)) == 2

    invalidas = (
        ({"apellido_paterno": "Apellido", "turno_empleado_id": int(turno_id)}, None),
        (
            {
                "nombres": "   ",
                "apellido_paterno": "Apellido",
                "turno_empleado_id": int(turno_id),
            },
            str(uuid4()),
        ),
        (
            {
                "nombres": "Ana",
                "apellido_paterno": "Apellido",
                "turno_empleado_id": int(turno_id),
                "esta_activo": False,
            },
            str(uuid4()),
        ),
        (
            {
                "nombres": "Ana",
                "apellido_paterno": "Apellido",
                "turno_empleado_id": True,
            },
            str(uuid4()),
        ),
    )
    for cuerpo, clave_invalida in invalidas:
        headers = {"Idempotency-Key": clave_invalida} if clave_invalida else {}
        respuesta = client.post(RUTA_EMPLEADOS, headers=headers, json=cuerpo)
        assert respuesta.status_code == 422
        assert respuesta.json() == {"detail": "Solicitud invalida"}
        assert respuesta.headers["cache-control"] == "no-store"

    turno_inexistente = client.post(
        RUTA_EMPLEADOS,
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "nombres": "Ana",
            "apellido_paterno": "Apellido",
            "turno_empleado_id": 999_999_999,
        },
    )
    assert turno_inexistente.status_code == 422
    assert db.scalar(select(func.count()).select_from(Empleado)) == 2


def test_lista_paginada_y_actualizacion_de_estado_sin_eliminar(
    client: TestClient,
    db: Session,
) -> None:
    _habilitar_modalidad(db)
    usuario_id = _crear_usuario(db, RolUsuario.OWNER.value)
    _usar_sesion(client, _crear_sesion(db, usuario_id))
    turno_id = _turno_id(client)
    for indice in range(11):
        _crear_empleado(client, turno_id, nombres=f"Persona {indice:02d}")

    segunda_pagina = client.get(RUTA_EMPLEADOS, params={"pagina": 2})
    assert segunda_pagina.status_code == 200
    assert segunda_pagina.json()["pagina"] == 2
    assert segunda_pagina.json()["tamano_pagina"] == 10
    assert segunda_pagina.json()["total"] == 11
    assert segunda_pagina.json()["total_paginas"] == 2
    assert len(segunda_pagina.json()["empleados"]) == 1

    ultima_pagina = client.get(RUTA_EMPLEADOS, params={"pagina": 500})
    assert ultima_pagina.json()["pagina"] == 2

    empleado = segunda_pagina.json()["empleados"][0]
    empleado_id = empleado["id"]
    assert empleado["codigo_empleado"] == formatear_codigo_empleado(
        int(empleado_id)
    )
    desactivado = client.patch(
        f"{RUTA_EMPLEADOS}/{empleado_id}/estado",
        json={"esta_activo": False, "revision_esperada": 1},
    )
    assert desactivado.status_code == 200
    assert desactivado.json()["id"] == empleado_id
    assert desactivado.json()["codigo_empleado"] == empleado["codigo_empleado"]
    assert desactivado.json()["esta_activo"] is False
    assert desactivado.json()["revision_estado"] == 2

    obsoleto = client.patch(
        f"{RUTA_EMPLEADOS}/{empleado_id}/estado",
        json={"esta_activo": True, "revision_esperada": 1},
    )
    assert obsoleto.status_code == 409
    assert obsoleto.headers["cache-control"] == "no-store"

    activado = client.patch(
        f"{RUTA_EMPLEADOS}/{empleado_id}/estado",
        json={"esta_activo": True, "revision_esperada": 2},
    )
    assert activado.status_code == 200
    assert activado.json()["id"] == empleado_id
    assert activado.json()["esta_activo"] is True
    assert activado.json()["revision_estado"] == 3

    repetido = client.patch(
        f"{RUTA_EMPLEADOS}/{empleado_id}/estado",
        json={"esta_activo": True, "revision_esperada": 1},
    )
    assert repetido.status_code == 200
    assert repetido.json()["revision_estado"] == 3

    inexistente = client.patch(
        f"{RUTA_EMPLEADOS}/999999999/estado",
        json={"esta_activo": False, "revision_esperada": 1},
    )
    assert inexistente.status_code == 404
    assert client.delete(f"{RUTA_EMPLEADOS}/{empleado_id}").status_code == 404
    assert db.scalar(select(func.count()).select_from(Empleado)) == 11
    assert db.get(Empleado, int(empleado_id)) is not None


def test_todas_las_modalidades_aplican_a_cada_operacion(
    client: TestClient,
    db: Session,
) -> None:
    usuario_id = _crear_usuario(db, RolUsuario.OWNER.value)
    _usar_sesion(client, _crear_sesion(db, usuario_id))

    revision = 0
    respuesta_mixta: dict[str, object] | None = None
    turno_id = ""
    for modalidad in ("PRIVADO", "MIXTO"):
        cambio = cambiar_modalidad_estacionamiento(
            db,
            modalidad,
            revision_esperada=revision,
        )
        assert cambio.configuracion is not None
        revision = cambio.configuracion.revision
        listado = client.get(RUTA_EMPLEADOS)
        assert listado.status_code == 200
        assert (
            client.post(
                RUTA_EMPLEADOS,
                headers={"Idempotency-Key": str(uuid4())},
                json={
                    "nombres": "Modalidad",
                    "apellido_paterno": modalidad,
                    "turno_empleado_id": int(_turno_id(client)),
                },
            ).status_code
            == 201
        )
        empleado = client.get(RUTA_EMPLEADOS).json()["empleados"][-1]
        assert (
            client.patch(
                f"{RUTA_EMPLEADOS}/{empleado['id']}/estado",
                json={
                    "esta_activo": False,
                    "revision_esperada": empleado["revision_estado"],
                },
            ).status_code
            == 200
        )
        turno_id = empleado["turno"]["id"]
        if modalidad == "MIXTO":
            respuesta_mixta = empleado

    cambio_publico = cambiar_modalidad_estacionamiento(
        db,
        "PUBLICO",
        revision_esperada=revision,
    )
    assert cambio_publico.configuracion is not None
    assert respuesta_mixta is not None
    registro_publico = client.post(
        RUTA_EMPLEADOS,
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "nombres": "No permitido",
            "apellido_paterno": "Publico",
            "turno_empleado_id": int(turno_id),
        },
    )
    estado_publico = client.patch(
        f"{RUTA_EMPLEADOS}/{respuesta_mixta['id']}/estado",
        json={"esta_activo": False, "revision_esperada": 1},
    )
    assert client.get(RUTA_EMPLEADOS).status_code == 409
    assert registro_publico.status_code == 409
    assert estado_publico.status_code == 409
    assert db.scalar(select(func.count()).select_from(Empleado)) == 2


def test_cambios_concurrentes_repetidos_incrementan_una_sola_revision(
    db: Session,
) -> None:
    _habilitar_modalidad(db)
    turno_id = db.scalar(select(TurnoEmpleado.id).order_by(TurnoEmpleado.id).limit(1))
    assert turno_id is not None
    creado = registrar_empleado(
        db,
        nombres="Concurrencia",
        apellido_paterno="Prueba",
        apellido_materno=None,
        turno_empleado_id=turno_id,
        clave_solicitud=uuid4(),
    )
    db.rollback()
    motor = db.get_bind()
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    barrera = Barrier(2)

    def desactivar() -> int:
        with fabrica() as sesion:
            barrera.wait(timeout=10)
            resultado = cambiar_estado_empleado(
                sesion,
                empleado_id=creado.empleado.id,
                esta_activo=False,
                revision_esperada=1,
            )
            return resultado.revision_estado

    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        tareas = [ejecutor.submit(desactivar), ejecutor.submit(desactivar)]
        resultados = sorted([tarea.result(timeout=20) for tarea in tareas])

    assert resultados == [2, 2]
    db.rollback()
    empleado = db.get(Empleado, creado.empleado.id)
    assert empleado is not None
    assert empleado.esta_activo is False
    assert empleado.revision_estado == 2
