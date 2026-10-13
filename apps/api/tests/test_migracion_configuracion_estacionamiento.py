"""Pruebas de upgrade, preservacion y downgrade de la modalidad."""

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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION_ANTERIOR = "20261008_0001"
REVISION_NUEVA = "20261010_0001"
REVISION_SUSPENSION = "20261012_0001"


@pytest.fixture
def migration_database(database_url: URL) -> Generator[tuple[URL, dict[str, str]]]:
    """Prepara una base temporal en la revision anterior a la modalidad."""

    nombre = f"smart_parking_modalidad_migration_{uuid4().hex}"
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
    migracion_anterior = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", REVISION_ANTERIOR],
        cwd=PROJECT_ROOT,
        env=entorno,
        capture_output=True,
        text=True,
        check=False,
    )
    if migracion_anterior.returncode != 0:
        with motor_admin.connect() as conexion:
            conexion.execute(text(f'DROP DATABASE "{nombre}" WITH (FORCE)'))
        motor_admin.dispose()
        pytest.fail("No se pudo preparar la base temporal de migracion.")

    try:
        yield url_temporal, entorno
    finally:
        with motor_admin.connect() as conexion:
            conexion.execute(text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))
        motor_admin.dispose()


def ejecutar_alembic(
    entorno: dict[str, str],
    *argumentos: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *argumentos],
        cwd=PROJECT_ROOT,
        env=entorno,
        capture_output=True,
        text=True,
        check=False,
    )


def test_upgrade_crea_modalidad_vacia_y_preserva_cajones_eventos_y_secuencias(
    migration_database: tuple[URL, dict[str, str]],
) -> None:
    url, entorno = migration_database
    motor = create_engine(url, pool_pre_ping=True)
    with motor.begin() as conexion:
        conexion.execute(
            text("UPDATE estado_eventos_tiempo_real SET ultimo_id = 574 WHERE id = 1")
        )
        conexion.execute(
            text(
                "INSERT INTO eventos_tiempo_real "
                "(id, recurso_tipo, recurso_id, tipo) "
                "VALUES (574, 'operador', 777, 'operador.actualizado')"
            )
        )
    with motor.connect() as conexion:
        cajones_antes = conexion.execute(
            text(
                "SELECT numero, estado_fisico, estado_operativo, motivo_operativo "
                "FROM cajones ORDER BY numero"
            )
        ).all()
        eventos_antes = conexion.execute(
            text(
                "SELECT id, recurso_tipo, recurso_id, tipo, datos "
                "FROM eventos_tiempo_real ORDER BY id"
            )
        ).all()
        ultimo_id_antes = conexion.scalar(
            text("SELECT ultimo_id FROM estado_eventos_tiempo_real WHERE id = 1")
        )
        secuencias_antes = {
            str(fila[0]): fila[1]
            for fila in conexion.execute(
                text(
                    "SELECT sequencename, last_value FROM pg_sequences "
                    "WHERE schemaname = current_schema()"
                )
            ).all()
        }

    upgrade = ejecutar_alembic(entorno, "upgrade", REVISION_NUEVA)
    assert upgrade.returncode == 0, upgrade.stderr

    with motor.connect() as conexion:
        cajones_despues = conexion.execute(
            text(
                "SELECT numero, estado_fisico, estado_operativo, motivo_operativo "
                "FROM cajones ORDER BY numero"
            )
        ).all()
        eventos_despues = conexion.execute(
            text(
                "SELECT id, recurso_tipo, recurso_id, tipo, datos "
                "FROM eventos_tiempo_real ORDER BY id"
            )
        ).all()
        secuencias_despues = {
            str(fila[0]): fila[1]
            for fila in conexion.execute(
                text(
                    "SELECT sequencename, last_value FROM pg_sequences "
                    "WHERE schemaname = current_schema()"
                )
            ).all()
        }
        assert (
            conexion.scalar(text("SELECT count(*) FROM configuracion_estacionamiento"))
            == 0
        )
        assert (
            conexion.scalar(
                text("SELECT count(*) FROM historial_modalidad_estacionamiento")
            )
            == 0
        )
        assert (
            conexion.scalar(
                text("SELECT ultimo_id FROM estado_eventos_tiempo_real WHERE id = 1")
            )
            == ultimo_id_antes
        )

    assert cajones_despues == cajones_antes
    assert eventos_despues == eventos_antes
    assert {nombre: secuencias_despues[nombre] for nombre in secuencias_antes} == (
        secuencias_antes
    )
    assert len(cajones_despues) == 8
    assert inspect(motor).has_table("configuracion_estacionamiento")
    assert inspect(motor).has_table("historial_modalidad_estacionamiento")

    downgrade = ejecutar_alembic(entorno, "downgrade", REVISION_ANTERIOR)
    assert downgrade.returncode == 0, downgrade.stderr
    assert not inspect(motor).has_table("configuracion_estacionamiento")
    assert not inspect(motor).has_table("historial_modalidad_estacionamiento")
    motor.dispose()


def test_downgrade_rechaza_eliminar_una_modalidad_persistida(
    migration_database: tuple[URL, dict[str, str]],
) -> None:
    url, entorno = migration_database
    motor = create_engine(url, pool_pre_ping=True)
    upgrade = ejecutar_alembic(entorno, "upgrade", REVISION_NUEVA)
    assert upgrade.returncode == 0, upgrade.stderr

    with motor.begin() as conexion:
        conexion.execute(
            text(
                "INSERT INTO configuracion_estacionamiento "
                "(id, modalidad, revision) VALUES (1, 'PRIVADO', 1)"
            )
        )

    downgrade = ejecutar_alembic(entorno, "downgrade", REVISION_ANTERIOR)
    assert downgrade.returncode != 0
    assert "No se puede revertir" in downgrade.stderr
    actual = ejecutar_alembic(entorno, "current")
    assert actual.returncode == 0
    assert REVISION_NUEVA in actual.stdout
    assert inspect(motor).has_table("configuracion_estacionamiento")
    motor.dispose()


def test_upgrade_suspension_preserva_configuracion_historial_y_falta_de_defaults(
    migration_database: tuple[URL, dict[str, str]],
) -> None:
    url, entorno = migration_database
    motor = create_engine(url, pool_pre_ping=True)
    base_modalidad = ejecutar_alembic(entorno, "upgrade", REVISION_NUEVA)
    assert base_modalidad.returncode == 0, base_modalidad.stderr

    fecha_anterior = "2000-01-01 00:00:00+00"
    with motor.begin() as conexion:
        conexion.execute(
            text(
                "INSERT INTO configuracion_estacionamiento "
                "(id, modalidad, revision, actualizado_en) "
                "VALUES (1, 'MIXTO', 4, :actualizado_en)"
            ),
            {"actualizado_en": fecha_anterior},
        )
        conexion.execute(
            text(
                "INSERT INTO historial_modalidad_estacionamiento "
                "(configuracion_id, revision, modalidad_anterior, modalidad_nueva) "
                "VALUES (1, 4, 'PUBLICO', 'MIXTO')"
            )
        )

    upgrade = ejecutar_alembic(entorno, "upgrade", REVISION_SUSPENSION)
    assert upgrade.returncode == 0, upgrade.stderr

    with motor.connect() as conexion:
        configuracion = conexion.execute(
            text(
                "SELECT modalidad, revision, actualizado_en, acceso_suspendido "
                "FROM configuracion_estacionamiento WHERE id = 1"
            )
        ).one()
        historial = conexion.execute(
            text(
                "SELECT configuracion_id, revision, modalidad_anterior, "
                "modalidad_nueva FROM historial_modalidad_estacionamiento"
            )
        ).all()
        assert configuracion.modalidad == "MIXTO"
        assert configuracion.revision == 4
        assert configuracion.actualizado_en.isoformat().startswith("2000-01-01")
        assert configuracion.acceso_suspendido is False
        assert historial == [(1, 4, "PUBLICO", "MIXTO")]

    downgrade = ejecutar_alembic(entorno, "downgrade", "20261011_0007")
    assert downgrade.returncode == 0, downgrade.stderr
    assert all(
        columna["name"] != "acceso_suspendido"
        for columna in inspect(motor).get_columns("configuracion_estacionamiento")
    )
    motor.dispose()


def test_upgrade_suspension_no_crea_modalidad_y_downgrade_protege_estado_activo(
    migration_database: tuple[URL, dict[str, str]],
) -> None:
    url, entorno = migration_database
    motor = create_engine(url, pool_pre_ping=True)
    upgrade = ejecutar_alembic(entorno, "upgrade", REVISION_SUSPENSION)
    assert upgrade.returncode == 0, upgrade.stderr

    with motor.connect() as conexion:
        assert (
            conexion.scalar(
                text("SELECT count(*) FROM configuracion_estacionamiento")
            )
            == 0
        )

    with motor.begin() as conexion:
        conexion.execute(
            text(
                "INSERT INTO configuracion_estacionamiento "
                "(id, modalidad, revision, acceso_suspendido) "
                "VALUES (1, 'PRIVADO', 2, TRUE)"
            )
        )

    downgrade = ejecutar_alembic(entorno, "downgrade", "20261011_0007")
    assert downgrade.returncode != 0
    assert "No se puede revertir" in downgrade.stderr
    actual = ejecutar_alembic(entorno, "current")
    assert actual.returncode == 0
    assert REVISION_SUSPENSION in actual.stdout
    assert any(
        columna["name"] == "acceso_suspendido"
        for columna in inspect(motor).get_columns("configuracion_estacionamiento")
    )
    motor.dispose()
