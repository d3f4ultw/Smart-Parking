"""Upgrade y downgrade protegido de la base de cajones."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION_ANTERIOR = "20261004_0001"
REVISION_NUEVA = "20261006_0001"
REVISION_MOTIVO_OPCIONAL = "20261008_0001"


@pytest.fixture
def migration_database(database_url: URL) -> Generator[tuple[URL, dict[str, str]]]:
    """Crea una base descartable en el head actual anterior a cajones."""

    nombre = f"smart_parking_cajones_migration_{uuid4().hex}"
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
        pytest.fail("No se pudo preparar la base temporal para la migracion.")

    try:
        yield url_temporal, entorno
    finally:
        with motor_admin.connect() as conexion:
            conexion.execute(text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))
        motor_admin.dispose()


def _ejecutar_alembic(
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


def test_upgrade_preserva_journal_inicializa_ocho_cajones_y_permite_downgrade_limpio(
    migration_database: tuple[URL, dict[str, str]],
) -> None:
    url, entorno = migration_database
    motor = create_engine(url, pool_pre_ping=True)
    with motor.begin() as conexion:
        conexion.execute(
            text("UPDATE estado_eventos_tiempo_real SET ultimo_id = 41 WHERE id = 1")
        )
        conexion.execute(
            text(
                "INSERT INTO eventos_tiempo_real "
                "(id, recurso_tipo, recurso_id, tipo) "
                "VALUES (41, 'operador', 777, 'operador.actualizado')"
            )
        )

    upgrade = _ejecutar_alembic(entorno, "upgrade", REVISION_NUEVA)
    assert upgrade.returncode == 0

    with motor.connect() as conexion:
        filas = conexion.execute(
            text(
                "SELECT numero, estado_fisico, estado_operativo, motivo_operativo, "
                "estado_fisico_actualizado_en, estado_operativo_actualizado_en, "
                "creado_en FROM cajones ORDER BY numero"
            )
        ).all()
        assert [fila.numero for fila in filas] == list(range(1, 9))
        assert all(fila.estado_fisico == "DESCONOCIDO" for fila in filas)
        assert all(fila.estado_operativo == "DISPONIBLE" for fila in filas)
        assert all(fila.motivo_operativo is None for fila in filas)
        assert all(fila.estado_fisico_actualizado_en is None for fila in filas)
        assert all(
            fila.estado_operativo_actualizado_en == fila.creado_en for fila in filas
        )
        evento_historico = conexion.execute(
            text(
                "SELECT id, recurso_tipo, recurso_id, tipo, datos "
                "FROM eventos_tiempo_real WHERE id = 41"
            )
        ).one()
        assert tuple(evento_historico) == (
            41,
            "operador",
            777,
            "operador.actualizado",
            None,
        )
        tipo_datos = conexion.scalar(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND table_name = 'eventos_tiempo_real' AND column_name = 'datos'"
            )
        )
        assert tipo_datos == "jsonb"

    downgrade = _ejecutar_alembic(entorno, "downgrade", REVISION_ANTERIOR)
    assert downgrade.returncode == 0
    with motor.connect() as conexion:
        assert conexion.scalar(text("SELECT count(*) FROM eventos_tiempo_real")) == 1
        assert (
            conexion.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema = 'public' "
                    "AND table_name = 'eventos_tiempo_real' AND column_name = 'datos'"
                )
            )
            == 0
        )
    motor.dispose()


def test_downgrade_rechaza_estado_o_eventos_de_cajon_utilizados(
    migration_database: tuple[URL, dict[str, str]],
) -> None:
    url, entorno = migration_database
    motor = create_engine(url, pool_pre_ping=True)
    upgrade = _ejecutar_alembic(entorno, "upgrade", REVISION_NUEVA)
    assert upgrade.returncode == 0

    with motor.begin() as conexion:
        conexion.execute(
            text(
                "UPDATE cajones SET estado_fisico = 'OCUPADO', "
                "estado_fisico_actualizado_en = now() WHERE numero = 1"
            )
        )
    downgrade_con_estado = _ejecutar_alembic(entorno, "downgrade", REVISION_ANTERIOR)
    assert downgrade_con_estado.returncode != 0
    assert "No se puede revertir" in downgrade_con_estado.stderr

    datos = {
        "cajon_id": 1,
        "numero": 1,
        "estado_fisico": "OCUPADO",
        "estado_operativo": "DISPONIBLE",
        "motivo_operativo": None,
        "estado_efectivo": "OCUPADO",
        "estado_fisico_actualizado_en": "2026-10-06T12:00:00+00:00",
        "estado_operativo_actualizado_en": "2026-10-06T12:00:00+00:00",
        "actualizado_en": "2026-10-06T12:00:00+00:00",
    }
    with motor.begin() as conexion:
        conexion.execute(
            text("UPDATE estado_eventos_tiempo_real SET ultimo_id = 1 WHERE id = 1")
        )
        conexion.execute(
            text(
                "INSERT INTO eventos_tiempo_real "
                "(id, recurso_tipo, recurso_id, tipo, datos) "
                "VALUES (1, 'cajon', 1, 'cajon.actualizado', CAST(:datos AS jsonb))"
            ),
            {"datos": json.dumps(datos)},
        )
    downgrade_con_evento = _ejecutar_alembic(entorno, "downgrade", REVISION_ANTERIOR)
    assert downgrade_con_evento.returncode != 0
    assert "No se puede revertir" in downgrade_con_evento.stderr
    actual = _ejecutar_alembic(entorno, "current")
    assert actual.returncode == 0
    assert REVISION_NUEVA in actual.stdout
    motor.dispose()


def test_migracion_permite_motivo_opcional_y_protege_downgrade(
    migration_database: tuple[URL, dict[str, str]],
) -> None:
    _url, entorno = migration_database
    upgrade = _ejecutar_alembic(entorno, "upgrade", REVISION_MOTIVO_OPCIONAL)
    assert upgrade.returncode == 0

    motor = create_engine(_url, pool_pre_ping=True)
    with motor.begin() as conexion:
        conexion.execute(
            text(
                "UPDATE cajones SET estado_operativo = 'MANTENIMIENTO', "
                "motivo_operativo = NULL WHERE numero = 1"
            )
        )
        conexion.execute(
            text(
                "UPDATE cajones SET estado_operativo = 'FUERA_DE_SERVICIO', "
                "motivo_operativo = NULL WHERE numero = 2"
            )
        )

    downgrade_inseguro = _ejecutar_alembic(entorno, "downgrade", REVISION_NUEVA)
    assert downgrade_inseguro.returncode != 0
    assert "No se puede revertir" in downgrade_inseguro.stderr
    actual = _ejecutar_alembic(entorno, "current")
    assert actual.returncode == 0
    assert REVISION_MOTIVO_OPCIONAL in actual.stdout

    with motor.begin() as conexion:
        conexion.execute(
            text(
                "UPDATE cajones SET motivo_operativo = 'Motivo de prueba' "
                "WHERE numero IN (1, 2)"
            )
        )

    downgrade_seguro = _ejecutar_alembic(entorno, "downgrade", REVISION_NUEVA)
    assert downgrade_seguro.returncode == 0
    motor.dispose()
