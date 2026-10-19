from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION_EMPLEADOS = "20261019_0001"
REVISION_ANTERIOR = "20261018_0002"


@pytest.fixture
def base_en_revision_anterior() -> Generator[tuple[URL, dict[str, str]]]:
    """Prepara un PostgreSQL temporal en la cabeza anterior al nuevo directorio."""

    ajustes = get_settings()
    nombre_temporal = f"smart_parking_empleados_migration_{uuid4().hex}"
    url_temporal = ajustes.model_copy(
        update={"database_name": nombre_temporal}
    ).database_url
    url_admin = ajustes.model_copy(update={"database_name": "postgres"}).database_url
    motor_admin = create_engine(
        url_admin,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    creada = False
    entorno = os.environ.copy()
    entorno["DATABASE_NAME"] = nombre_temporal

    try:
        with motor_admin.connect() as conexion:
            conexion.execute(text(f'CREATE DATABASE "{nombre_temporal}"'))
        creada = True
        migracion = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", REVISION_ANTERIOR],
            cwd=PROJECT_ROOT,
            env=entorno,
            capture_output=True,
            text=True,
            check=False,
        )
        if migracion.returncode != 0:
            pytest.fail("No fue posible preparar la cabeza Alembic anterior")

        motor_temporal = create_engine(url_temporal, pool_pre_ping=True)
        with motor_temporal.begin() as conexion:
            conexion.execute(
                text(
                    "INSERT INTO configuracion_estacionamiento "
                    "(id, modalidad, revision, revision_horarios, acceso_suspendido) "
                    "VALUES (1, 'MIXTO', 7, 3, false)"
                )
            )
            conexion.execute(
                text(
                    "INSERT INTO turnos_empleados "
                    "(configuracion_estacionamiento_id, codigo, hora_inicio, hora_fin) "
                    "VALUES (1, 'MATUTINO', '06:00', '14:00'), "
                    "(1, 'VESPERTINO', '14:00', '22:00'), "
                    "(1, 'NOCTURNO', '22:00', '06:00'), "
                    "(1, 'SIN_RESTRICCION', NULL, NULL)"
                )
            )
        motor_temporal.dispose()
        yield url_temporal, entorno
    finally:
        if creada:
            with motor_admin.connect() as conexion:
                conexion.execute(
                    text(f'DROP DATABASE IF EXISTS "{nombre_temporal}" WITH (FORCE)')
                )
        motor_admin.dispose()


def test_migracion_aditiva_preserva_configuracion_y_turnos_compartidos(
    base_en_revision_anterior: tuple[URL, dict[str, str]],
) -> None:
    url_temporal, entorno = base_en_revision_anterior
    motor = create_engine(url_temporal, pool_pre_ping=True)
    try:
        migracion = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=PROJECT_ROOT,
            env=entorno,
            capture_output=True,
            text=True,
            check=False,
        )
        assert migracion.returncode == 0, "No se pudo crear la tabla de empleados"

        with motor.begin() as conexion:
            assert conexion.scalar(text("SELECT version_num FROM alembic_version")) == (
                REVISION_EMPLEADOS
            )
            assert "empleados" in set(inspect(conexion).get_table_names())
            assert conexion.execute(
                text(
                    "SELECT modalidad, revision, revision_horarios, acceso_suspendido "
                    "FROM configuracion_estacionamiento WHERE id = 1"
                )
            ).one() == ("MIXTO", 7, 3, False)
            turnos = conexion.execute(
                text(
                    "SELECT codigo, hora_inicio::text, hora_fin::text "
                    "FROM turnos_empleados ORDER BY codigo"
                )
            ).all()
            assert turnos == [
                ("MATUTINO", "06:00:00", "14:00:00"),
                ("NOCTURNO", "22:00:00", "06:00:00"),
                ("SIN_RESTRICCION", None, None),
                ("VESPERTINO", "14:00:00", "22:00:00"),
            ]
            assert conexion.scalar(text("SELECT count(*) FROM empleados")) == 0

            turno_id = conexion.scalar(
                text(
                    "SELECT id FROM turnos_empleados "
                    "WHERE configuracion_estacionamiento_id = 1 "
                    "AND codigo = 'MATUTINO'"
                )
            )
            empleado_id = conexion.scalar(
                text(
                    "INSERT INTO empleados "
                    "(configuracion_estacionamiento_id, turno_empleado_id, nombres, "
                    "apellido_paterno, clave_solicitud) "
                    "VALUES (1, :turno_id, 'Ana', 'Prueba', "
                    "CAST(:clave AS uuid)) RETURNING id"
                ).bindparams(turno_id=turno_id, clave=str(uuid4()))
            )
            empleado = conexion.execute(
                text(
                    "SELECT id, esta_activo, revision_estado, creado_en, "
                    "actualizado_en FROM empleados WHERE id = :empleado_id"
                ),
                {"empleado_id": empleado_id},
            ).one()
            assert empleado.id == empleado_id
            assert empleado.esta_activo is True
            assert empleado.revision_estado == 1
            assert empleado.creado_en is not None
            assert empleado.actualizado_en is not None

        with pytest.raises(DBAPIError):
            with motor.begin() as conexion:
                conexion.execute(
                    text("UPDATE empleados SET id = id + 100 WHERE id = :id"),
                    {"id": empleado_id},
                )

        with pytest.raises(IntegrityError):
            with motor.begin() as conexion:
                conexion.execute(
                    text(
                        "INSERT INTO empleados "
                        "(configuracion_estacionamiento_id, turno_empleado_id, "
                        "nombres, apellido_paterno, clave_solicitud) "
                    "VALUES (1, 999999999, 'Eva', 'Prueba', CAST(:clave AS uuid))"
                    ),
                    {"clave": str(uuid4())},
                )

        rechazo_downgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", REVISION_ANTERIOR],
            cwd=PROJECT_ROOT,
            env=entorno,
            capture_output=True,
            text=True,
            check=False,
        )
        assert rechazo_downgrade.returncode != 0
        with motor.connect() as conexion:
            assert conexion.scalar(text("SELECT version_num FROM alembic_version")) == (
                REVISION_EMPLEADOS
            )
            assert conexion.scalar(text("SELECT count(*) FROM empleados")) == 1

        with motor.begin() as conexion:
            conexion.execute(
                text("DELETE FROM empleados WHERE id = :id"),
                {"id": empleado_id},
            )
        downgrade_vacio = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", REVISION_ANTERIOR],
            cwd=PROJECT_ROOT,
            env=entorno,
            capture_output=True,
            text=True,
            check=False,
        )
        assert downgrade_vacio.returncode == 0
        with motor.connect() as conexion:
            assert conexion.scalar(text("SELECT version_num FROM alembic_version")) == (
                REVISION_ANTERIOR
            )
            assert "empleados" not in set(inspect(conexion).get_table_names())
            assert conexion.scalar(text("SELECT count(*) FROM turnos_empleados")) == 4
    finally:
        motor.dispose()
