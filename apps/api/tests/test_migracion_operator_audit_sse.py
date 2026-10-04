"""Compatibilidad y rollback protegido de la migracion de auditoria/SSE."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION_ANTERIOR = "20261002_0003"
REVISION_NUEVA = "20261003_0001"


@pytest.fixture
def migration_database(database_url: URL) -> Generator[tuple[URL, dict[str, str]]]:
    """Crea una base descartable y la deja en el head anterior a la feature."""

    nombre = f"smart_parking_migration_{uuid4().hex}"
    url_temporal = database_url.set(database=nombre)
    url_admin = database_url.set(database="postgres")
    motor_admin = create_engine(
        url_admin,
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
    if resultado.returncode != 0:
        with motor_admin.connect() as conexion:
            conexion.execute(text(f'DROP DATABASE "{nombre}" WITH (FORCE)'))
        motor_admin.dispose()
        pytest.fail("No se pudo preparar la base temporal en el head anterior.")

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


def test_upgrade_preserva_timestamps_y_downgrade_protege_atribuciones(
    migration_database: tuple[URL, dict[str, str]],
) -> None:
    url, entorno = migration_database
    motor = create_engine(url, pool_pre_ping=True)
    admin_fecha = datetime(2020, 2, 3, 4, 5, 6, tzinfo=UTC)
    operador_fecha = datetime(2021, 6, 7, 8, 9, 10, tzinfo=UTC)
    with motor.begin() as conexion:
        conexion.execute(
            text(
                "INSERT INTO usuarios "
                "(nombre, apellido_paterno, apellido_materno, correo, "
                "contrasena_hash, rol, correo_verificado, debe_cambiar_contrasena, "
                "esta_activo, creado_en, actualizado_en) "
                "VALUES ('Admin', 'Prueba', 'Sintetico', "
                "'admin-migration@example.com', "
                "'hash-sintetico', 'ADMIN', true, false, true, :fecha, :fecha)"
            ),
            {"fecha": admin_fecha},
        )
        conexion.execute(
            text(
                "INSERT INTO usuarios "
                "(nombre, apellido_paterno, apellido_materno, correo, "
                "contrasena_hash, rol, correo_verificado, debe_cambiar_contrasena, "
                "esta_activo, creado_en, actualizado_en) "
                "VALUES ('Operador', 'Prueba', 'Sintetico', "
                "'operador-migration@example.com', 'hash-sintetico', 'OPERADOR', "
                "true, false, true, :fecha, :fecha)"
            ),
            {"fecha": operador_fecha},
        )

    upgrade = _ejecutar_alembic(entorno, "upgrade", "head")
    assert upgrade.returncode == 0
    with motor.connect() as conexion:
        filas = conexion.execute(
            text(
                "SELECT correo, creado_en, creado_por_usuario_id "
                "FROM usuarios WHERE correo IN "
                "('admin-migration@example.com', 'operador-migration@example.com') "
                "ORDER BY correo"
            )
        ).all()
        assert [
            (fila.correo, fila.creado_en, fila.creado_por_usuario_id)
            for fila in filas
        ] == [
            ("admin-migration@example.com", admin_fecha, None),
            ("operador-migration@example.com", operador_fecha, None),
        ]
        assert conexion.scalar(
            text(
                "SELECT count(*) FROM estado_eventos_operadores "
                "WHERE id = 1 AND ultimo_id = 0"
            )
        ) == 1
        assert conexion.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='usuarios' "
                "AND column_name='creado_en' AND data_type='timestamp with time zone' "
                "AND is_nullable='NO' "
                "AND column_default='CURRENT_TIMESTAMP'"
            )
        ) == 1
        assert conexion.scalar(
            text("SELECT to_regclass('public.ix_usuarios_creado_por_usuario_id')")
        ) == "ix_usuarios_creado_por_usuario_id"
        assert conexion.scalar(
            text(
                "SELECT count(*) FROM information_schema.referential_constraints "
                "WHERE constraint_name='fk_usuarios_creado_por_usuario_id_usuarios' "
                "AND delete_rule='RESTRICT'"
            )
        ) == 1
        for tabla in (
            "eventos_operadores",
            "estado_eventos_operadores",
            "conexiones_sse_admin",
        ):
            resultado_tabla = conexion.scalar(
                text("SELECT to_regclass(:tabla)"),
                {"tabla": f"public.{tabla}"},
            )
            assert resultado_tabla == tabla

    downgrade_limpio = _ejecutar_alembic(
        entorno,
        "downgrade",
        REVISION_ANTERIOR,
    )
    assert downgrade_limpio.returncode == 0
    with motor.connect() as conexion:
        assert conexion.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='usuarios' "
                "AND column_name='creado_por_usuario_id'"
            )
        ) == 0
        tabla_eventos = conexion.scalar(
            text("SELECT to_regclass('public.eventos_operadores')")
        )
        assert tabla_eventos is None

    upgrade_repetido = _ejecutar_alembic(entorno, "upgrade", "head")
    assert upgrade_repetido.returncode == 0
    with motor.begin() as conexion:
        admin_id = conexion.scalar(
            text(
                "SELECT id FROM usuarios "
                "WHERE correo='admin-migration@example.com'"
            )
        )
        conexion.execute(
            text(
                "UPDATE usuarios SET creado_por_usuario_id=:admin_id "
                "WHERE correo='operador-migration@example.com'"
            ),
            {"admin_id": admin_id},
        )

    downgrade_con_auditoria = _ejecutar_alembic(
        entorno,
        "downgrade",
        REVISION_ANTERIOR,
    )
    assert downgrade_con_auditoria.returncode != 0
    actual = _ejecutar_alembic(entorno, "current")
    assert actual.returncode == 0
    assert REVISION_NUEVA in actual.stdout
    with motor.connect() as conexion:
        assert conexion.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='usuarios' "
                "AND column_name='creado_por_usuario_id'"
            )
        ) == 1
    motor.dispose()
