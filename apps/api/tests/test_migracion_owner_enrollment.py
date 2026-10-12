from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION_BASE = "20261011_0001"
REVISION_OWNER = "20261011_0002"
REVISION_OWNER_WINDOW = "20261011_0003"


@pytest.fixture
def base_owner_database(database_url: URL):
    nombre = f"smart_parking_owner_enrollment_{uuid4().hex}"
    url = database_url.set(database=nombre)
    motor_admin = create_engine(
        database_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    with motor_admin.connect() as conexion:
        conexion.execute(text(f'CREATE DATABASE "{nombre}"'))
    entorno = os.environ.copy()
    entorno["DATABASE_NAME"] = nombre
    resultado = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", REVISION_BASE],
        cwd=PROJECT_ROOT,
        env=entorno,
        capture_output=True,
        text=True,
        check=False,
    )
    if resultado.returncode != 0:
        with motor_admin.connect() as conexion:
            conexion.execute(text(f'DROP DATABASE "{nombre}" WITH (FORCE)'))
        motor_admin.dispose()
        pytest.fail("No se pudo preparar la base aislada previa a Phase 2.")
    try:
        yield url, entorno
    finally:
        with motor_admin.connect() as conexion:
            conexion.execute(text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))
        motor_admin.dispose()


def _alembic(
    entorno: dict[str, str],
    accion: str,
    revision: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", accion, revision],
        cwd=PROJECT_ROOT,
        env=entorno,
        capture_output=True,
        text=True,
        check=False,
    )


def test_migracion_owner_agrega_estado_sin_modificar_usuarios(
    base_owner_database: tuple[URL, dict[str, str]],
) -> None:
    url, entorno = base_owner_database
    motor = create_engine(url, pool_pre_ping=True)
    with motor.begin() as conexion:
        usuario_id = conexion.scalar(
            text(
                "INSERT INTO usuarios (correo, contrasena_hash, rol, "
                "correo_verificado, debe_cambiar_contrasena, esta_activo) "
                "VALUES ('phase2-preservation@example.com', 'hash-de-prueba', "
                "'ADMIN', true, false, true) RETURNING id"
            )
        )

    upgrade = _alembic(entorno, "upgrade", REVISION_OWNER)
    assert upgrade.returncode == 0, "No se pudo aplicar la migracion Phase 2 aislada."

    inspector = inspect(motor)
    assert "cuentas_propietario" in inspector.get_table_names()
    assert "inscripciones_propietario" in inspector.get_table_names()
    with motor.connect() as conexion:
        usuario = conexion.execute(
            text("SELECT id, correo, rol, esta_activo FROM usuarios WHERE id=:id"),
            {"id": usuario_id},
        ).one()
        assert tuple(usuario) == (
            usuario_id,
            "phase2-preservation@example.com",
            "ADMIN",
            True,
        )
        assert conexion.scalar(text("SELECT count(*) FROM cuentas_propietario")) == 0
        assert (
            conexion.scalar(text("SELECT count(*) FROM inscripciones_propietario")) == 0
        )
        assert (
            conexion.scalar(
                text("SELECT count(*) FROM usuarios WHERE rol='OWNER' AND esta_activo")
            )
            == 0
        )

    with motor.begin() as conexion:
        inscripcion_id = conexion.scalar(
            text(
                "INSERT INTO inscripciones_propietario "
                "(correo, token_hash, expira_en, ultimo_envio_en, reenviados, "
                "creado_en) VALUES ("
                "'legacy@example.test', 'hash-legado', "
                "'2026-10-11 08:15:00+00', '2026-10-11 08:00:00+00', 1, "
                "'2026-10-11 08:00:00+00') RETURNING id"
            )
        )

    upgrade_window = _alembic(entorno, "upgrade", REVISION_OWNER_WINDOW)
    assert upgrade_window.returncode == 0, (
        "No se pudo aplicar la ventana OWNER aislada."
    )
    assert "proceso_expira_en" in {
        columna["name"]
        for columna in inspect(motor).get_columns("inscripciones_propietario")
    }
    with motor.connect() as conexion:
        fecha_proceso = conexion.scalar(
            text(
                "SELECT proceso_expira_en FROM inscripciones_propietario WHERE id=:id"
            ),
            {"id": inscripcion_id},
        )
        assert fecha_proceso.isoformat() == "2026-10-11T09:00:00+00:00"

    with pytest.raises(IntegrityError):
        with motor.begin() as conexion:
            conexion.execute(
                text(
                    "INSERT INTO inscripciones_propietario "
                    "(correo, token_hash, expira_en, proceso_expira_en, "
                    "ultimo_envio_en, reenviados) "
                    "VALUES ('resend@example.com', 'hash', now(), now(), now(), 4)"
                )
            )

    downgrade = _alembic(entorno, "downgrade", REVISION_BASE)
    assert downgrade.returncode == 0, "No se pudo revertir la migracion aislada."
    assert "cuentas_propietario" not in inspect(motor).get_table_names()
    assert "inscripciones_propietario" not in inspect(motor).get_table_names()
    with motor.connect() as conexion:
        assert (
            conexion.scalar(
                text("SELECT count(*) FROM usuarios WHERE id=:id"),
                {"id": usuario_id},
            )
            == 1
        )
    motor.dispose()
