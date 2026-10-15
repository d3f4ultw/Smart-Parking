"""Verifica el retiro forward-only de la semilla heredada de cajones."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION_ANTERIOR = "20261013_0001"
REVISION_VISION = "20261013_0002"
REVISION_CURSOR = "20261013_0003"


def test_migracion_vision_preserva_cursor_auth_configuracion_y_eventos_ajenos(
    database_url: URL,
) -> None:
    nombre = f"smart_parking_vision_migration_{uuid4().hex}"
    url_temporal = database_url.set(database=nombre)
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
        [sys.executable, "-m", "alembic", "upgrade", REVISION_ANTERIOR],
        cwd=PROJECT_ROOT,
        env=entorno,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resultado.returncode == 0

    motor = create_engine(url_temporal, pool_pre_ping=True)
    try:
        with motor.begin() as conexion:
            conexion.execute(
                text(
                    "INSERT INTO usuarios "
                    "(id, correo, contrasena_hash, rol, correo_verificado, "
                    "debe_cambiar_contrasena, esta_activo) "
                    "VALUES (1, 'vision-migration@example.invalid', 'synthetic-hash', "
                    "'OWNER', true, false, true)"
                )
            )
            conexion.execute(
                text(
                    "INSERT INTO sesiones (usuario_id, token_hash, expira_en) "
                    "VALUES (1, 'synthetic-session-hash', now() + interval '1 hour')"
                )
            )
            conexion.execute(
                text(
                    "INSERT INTO configuracion_estacionamiento "
                    "(id, modalidad, revision, acceso_suspendido) "
                    "VALUES (1, 'PRIVADO', 7, true)"
                )
            )
            conexion.execute(
                text(
                    "UPDATE estado_eventos_tiempo_real SET ultimo_id = 90 WHERE id = 1"
                )
            )
            conexion.execute(
                text(
                    "INSERT INTO eventos_tiempo_real "
                    "(id, recurso_tipo, recurso_id, tipo) "
                    "VALUES (80, 'operador', 1, 'operador.actualizado')"
                )
            )
            conexion.execute(
                text(
                    "INSERT INTO eventos_tiempo_real "
                    "(id, recurso_tipo, recurso_id, tipo, datos) "
                    "VALUES (81, 'cajon', 1, 'cajon.actualizado', '{}'::jsonb)"
                )
            )

        upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", REVISION_CURSOR],
            cwd=PROJECT_ROOT,
            env=entorno,
            capture_output=True,
            text=True,
            check=False,
        )
        assert upgrade.returncode == 0

        with motor.connect() as conexion:
            assert conexion.scalar(text("SELECT count(*) FROM cajones")) == 0
            assert (
                conexion.scalar(
                    text("SELECT next_c_number FROM vision_configuration WHERE id = 1")
                )
                == 1
            )
            assert (
                conexion.scalar(
                    text(
                        "SELECT ultimo_id FROM estado_eventos_tiempo_real WHERE id = 1"
                    )
                )
                == 90
            )
            assert (
                conexion.scalar(
                    text(
                        "SELECT count(*) FROM eventos_tiempo_real "
                        "WHERE recurso_tipo = 'cajon'"
                    )
                )
                == 0
            )
            assert (
                conexion.scalar(
                    text("SELECT count(*) FROM eventos_tiempo_real WHERE id = 80")
                )
                == 1
            )
            assert (
                conexion.scalar(text("SELECT count(*) FROM usuarios WHERE id = 1")) == 1
            )
            assert (
                conexion.scalar(
                    text("SELECT count(*) FROM sesiones WHERE usuario_id = 1")
                )
                == 1
            )
            assert (
                conexion.scalar(
                    text(
                        "SELECT acceso_suspendido FROM configuracion_estacionamiento "
                        "WHERE id = 1"
                    )
                )
                is True
            )

        downgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", REVISION_ANTERIOR],
            cwd=PROJECT_ROOT,
            env=entorno,
            capture_output=True,
            text=True,
            check=False,
        )
        assert downgrade.returncode != 0
    finally:
        motor.dispose()
        with motor_admin.connect() as conexion:
            conexion.execute(text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))
        motor_admin.dispose()


def test_migracion_reconstruye_cursor_ausente_desde_eventos_retenidos(
    database_url: URL,
) -> None:
    nombre = f"smart_parking_cursor_migration_{uuid4().hex}"
    url_temporal = database_url.set(database=nombre)
    motor_admin = create_engine(
        database_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    with motor_admin.connect() as conexion:
        conexion.execute(text(f'CREATE DATABASE "{nombre}"'))

    entorno = os.environ.copy()
    entorno["DATABASE_NAME"] = nombre
    motor = create_engine(url_temporal, pool_pre_ping=True)
    try:
        anterior = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", REVISION_VISION],
            cwd=PROJECT_ROOT,
            env=entorno,
            capture_output=True,
            text=True,
            check=False,
        )
        assert anterior.returncode == 0

        with motor.begin() as conexion:
            conexion.execute(
                text("DELETE FROM estado_eventos_tiempo_real WHERE id = 1")
            )
            conexion.execute(
                text(
                    "INSERT INTO eventos_tiempo_real "
                    "(id, recurso_tipo, recurso_id, tipo) "
                    "VALUES (80, 'operador', 1, 'operador.actualizado')"
                )
            )
            assert (
                conexion.scalar(
                    text("SELECT count(*) FROM estado_eventos_tiempo_real WHERE id = 1")
                )
                == 0
            )

        reparacion = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", REVISION_CURSOR],
            cwd=PROJECT_ROOT,
            env=entorno,
            capture_output=True,
            text=True,
            check=False,
        )
        assert reparacion.returncode == 0

        with motor.connect() as conexion:
            assert (
                conexion.scalar(
                    text(
                        "SELECT ultimo_id FROM estado_eventos_tiempo_real WHERE id = 1"
                    )
                )
                == 80
            )
    finally:
        motor.dispose()
        with motor_admin.connect() as conexion:
            conexion.execute(text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))
        motor_admin.dispose()
