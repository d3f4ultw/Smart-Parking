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
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION_ANTERIOR = "20261010_0002"
REVISION_NUEVA = "20261011_0001"


@pytest.fixture
def migration_database(database_url: URL) -> Generator[tuple[URL, dict[str, str]]]:
    """Crea una base temporal aislada en el head previo a OWNER."""

    nombre = f"smart_parking_owner_migration_{uuid4().hex}"
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
    preparacion = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", REVISION_ANTERIOR],
        cwd=PROJECT_ROOT,
        env=entorno,
        capture_output=True,
        text=True,
        check=False,
    )
    if preparacion.returncode != 0:
        with motor_admin.connect() as conexion:
            conexion.execute(text(f'DROP DATABASE "{nombre}" WITH (FORCE)'))
        motor_admin.dispose()
        pytest.fail("No se pudo preparar la base aislada previa a OWNER.")

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


def crear_usuarios_de_prueba(motor, cantidad: int = 2) -> tuple[int, ...]:
    with motor.begin() as conexion:
        return tuple(
            conexion.scalar(
                text(
                    "INSERT INTO usuarios "
                    "(correo, contrasena_hash, rol, correo_verificado, "
                    "debe_cambiar_contrasena, esta_activo) "
                    "VALUES (:correo, 'hash-de-prueba-no-utilizable', 'ADMIN', "
                    "true, false, true) RETURNING id"
                ),
                {"correo": f"owner-migration-{uuid4().hex}@example.com"},
            )
            for _ in range(cantidad)
        )


def test_migracion_permite_cero_o_un_owner_activo_y_rechaza_el_segundo(
    migration_database: tuple[URL, dict[str, str]],
) -> None:
    url, entorno = migration_database
    motor = create_engine(url, pool_pre_ping=True)
    usuarios = crear_usuarios_de_prueba(motor)

    upgrade = ejecutar_alembic(entorno, "upgrade", REVISION_NUEVA)
    assert upgrade.returncode == 0, "No se pudo aplicar la migracion aislada."

    with motor.connect() as conexion:
        assert (
            conexion.scalar(
                text(
                    "SELECT count(*) FROM usuarios WHERE rol = 'OWNER' AND esta_activo"
                )
            )
            == 0
        )
    with motor.begin() as conexion:
        conexion.execute(
            text("UPDATE usuarios SET rol = 'OWNER' WHERE id = :id"),
            {"id": usuarios[0]},
        )
    with motor.connect() as conexion:
        assert (
            conexion.scalar(
                text(
                    "SELECT count(*) FROM usuarios WHERE rol = 'OWNER' AND esta_activo"
                )
            )
            == 1
        )

    with pytest.raises(IntegrityError):
        with motor.begin() as conexion:
            conexion.execute(
                text("UPDATE usuarios SET rol = 'OWNER' WHERE id = :id"),
                {"id": usuarios[1]},
            )

    with motor.begin() as conexion:
        conexion.execute(
            text("UPDATE usuarios SET esta_activo = false WHERE id = :id"),
            {"id": usuarios[0]},
        )
        conexion.execute(
            text(
                "UPDATE usuarios SET rol = 'OWNER', esta_activo = false WHERE id = :id"
            ),
            {"id": usuarios[1]},
        )
    with motor.connect() as conexion:
        assert (
            conexion.scalar(
                text(
                    "SELECT count(*) FROM usuarios WHERE rol = 'OWNER' AND esta_activo"
                )
            )
            == 0
        )

    inspector = inspect(motor)
    indice = next(
        elemento
        for elemento in inspector.get_indexes("usuarios")
        if elemento["name"] == "uq_usuarios_owner_activo"
    )
    assert indice["unique"] is True
    assert indice["column_names"] == ["rol"]
    predicado = (indice.get("dialect_options") or {}).get("postgresql_where")
    assert predicado is not None
    assert "OWNER" in predicado
    assert "esta_activo" in predicado

    downgrade = ejecutar_alembic(entorno, "downgrade", REVISION_ANTERIOR)
    assert downgrade.returncode == 0, "No se pudo revertir la migracion aislada."
    assert not any(
        elemento["name"] == "uq_usuarios_owner_activo"
        for elemento in inspect(motor).get_indexes("usuarios")
    )
    with motor.connect() as conexion:
        assert conexion.scalar(text("SELECT count(*) FROM usuarios")) == 2
    motor.dispose()


def test_indice_rechaza_activaciones_concurrentes_de_dos_owner(
    migration_database: tuple[URL, dict[str, str]],
) -> None:
    url, entorno = migration_database
    motor = create_engine(url, pool_pre_ping=True)
    usuarios = crear_usuarios_de_prueba(motor)
    upgrade = ejecutar_alembic(entorno, "upgrade", REVISION_NUEVA)
    assert upgrade.returncode == 0, "No se pudo aplicar la migracion aislada."

    barrera = Barrier(2)

    def activar(usuario_id: int) -> str:
        with Session(motor) as sesion:
            try:
                barrera.wait(timeout=15)
                sesion.execute(
                    text("UPDATE usuarios SET rol = 'OWNER' WHERE id = :id"),
                    {"id": usuario_id},
                )
                sesion.commit()
                return "confirmado"
            except IntegrityError:
                sesion.rollback()
                return "rechazado_por_indice"

    with ThreadPoolExecutor(max_workers=2) as ejecutores:
        resultados = tuple(ejecutores.map(activar, usuarios))

    assert sorted(resultados) == ["confirmado", "rechazado_por_indice"]
    with motor.connect() as conexion:
        assert (
            conexion.scalar(
                text(
                    "SELECT count(*) FROM usuarios WHERE rol = 'OWNER' AND esta_activo"
                )
            )
            == 1
        )
    motor.dispose()
