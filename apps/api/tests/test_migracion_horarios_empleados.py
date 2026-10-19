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

from app.core.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def base_con_datos_previos() -> Generator[tuple[URL, URL]]:
    """Prepara una base temporal en la cabeza anterior con datos de estacionamiento."""

    ajustes = get_settings()
    nombre_temporal = f"smart_parking_schedules_migration_{uuid4().hex}"
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
    entorno_migracion = os.environ.copy()
    entorno_migracion["DATABASE_NAME"] = nombre_temporal

    try:
        with motor_admin.connect() as conexion:
            conexion.execute(text(f'CREATE DATABASE "{nombre_temporal}"'))
        creada = True

        migracion_base = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "20261018_0001"],
            cwd=PROJECT_ROOT,
            env=entorno_migracion,
            capture_output=True,
            text=True,
            check=False,
        )
        if migracion_base.returncode != 0:
            pytest.fail("No fue posible preparar la base temporal de migración")

        motor_temporal = create_engine(url_temporal, pool_pre_ping=True)
        with motor_temporal.begin() as conexion:
            conexion.execute(
                text(
                    "INSERT INTO configuracion_estacionamiento "
                    "(id, modalidad, revision, acceso_suspendido) "
                    "VALUES (1, 'MIXTO', 7, true)"
                )
            )
            conexion.execute(
                text(
                    "INSERT INTO usuarios "
                    "(id, correo, contrasena_hash, rol, correo_verificado, "
                    "debe_cambiar_contrasena, esta_activo) "
                    "VALUES (9001, 'migration@example.invalid', 'hash-sintetico', "
                    "'OWNER', true, false, true)"
                )
            )
            conexion.execute(
                text(
                    "INSERT INTO sesiones (usuario_id, token_hash, expira_en) "
                    "VALUES (9001, 'hash-sesion-sintetica', "
                    "now() + interval '1 hour')"
                )
            )
            conexion.execute(
                text(
                    "INSERT INTO historial_modalidad_estacionamiento "
                    "(configuracion_id, revision, modalidad_anterior, modalidad_nueva) "
                    "VALUES (1, 1, NULL, 'MIXTO')"
                )
            )
            conexion.execute(
                text(
                    "INSERT INTO cajones (numero, vision_zone_id, poligono, activa) "
                    "VALUES (77, 'aa000000-0000-4000-8000-000000000077', "
                    "'[[0.1,0.1],[0.9,0.1],[0.9,0.9],[0.1,0.9]]'::jsonb, true)"
                )
            )
        motor_temporal.dispose()
        yield url_temporal, url_admin
    finally:
        if creada:
            with motor_admin.connect() as conexion:
                conexion.execute(
                    text(f'DROP DATABASE IF EXISTS "{nombre_temporal}" WITH (FORCE)')
                )
        motor_admin.dispose()


def test_migracion_siembra_turnos_y_conserva_configuracion_y_datos_existentes(
    base_con_datos_previos: tuple[URL, URL],
) -> None:
    url_temporal, _url_admin = base_con_datos_previos
    motor = create_engine(url_temporal, pool_pre_ping=True)
    entorno_migracion = os.environ.copy()
    entorno_migracion["DATABASE_NAME"] = url_temporal.database or ""

    try:
        migracion = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "20261018_0002"],
            cwd=PROJECT_ROOT,
            env=entorno_migracion,
            capture_output=True,
            text=True,
            check=False,
        )
        assert migracion.returncode == 0, "No fue posible aplicar la migración temporal"

        with motor.connect() as conexion:
            tablas = set(inspect(conexion).get_table_names())
            configuracion = conexion.execute(
                text(
                    "SELECT modalidad, revision, revision_horarios, acceso_suspendido "
                    "FROM configuracion_estacionamiento WHERE id = 1"
                )
            ).one()
            assert tuple(configuracion) == ("MIXTO", 7, 1, True)
            assert conexion.scalar(text("SELECT count(*) FROM usuarios")) == 1
            assert conexion.scalar(text("SELECT count(*) FROM sesiones")) == 1
            assert (
                conexion.scalar(
                    text("SELECT count(*) FROM historial_modalidad_estacionamiento")
                )
                == 1
            )
            assert conexion.scalar(text("SELECT numero FROM cajones")) == 77
            assert (
                conexion.scalar(
                    text("SELECT count(*) FROM vision_calibration_lease")
                )
                == 1
            )
            assert "empleados" not in tablas

            turnos = conexion.execute(
                text(
                    "SELECT codigo, hora_inicio, hora_fin FROM turnos_empleados "
                    "ORDER BY codigo"
                )
            ).all()
            assert [fila.codigo for fila in turnos] == [
                "MATUTINO",
                "NOCTURNO",
                "SIN_RESTRICCION",
                "VESPERTINO",
            ]
            assert all(
                fila.hora_inicio is None and fila.hora_fin is None
                for fila in turnos
            )
            assert conexion.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20261018_0002"
            )
    finally:
        motor.dispose()
