"""Pruebas de migracion con una base temporal independiente."""

from __future__ import annotations

import os
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import create_engine, text

from app.core.config import Settings

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_migracion_preserva_filas_y_downgrade_protege_admin_pendiente() -> None:
    settings = Settings.model_validate(
        {
            "database_host": os.environ["DATABASE_HOST"],
            "database_port": os.environ["DATABASE_PORT"],
            "database_name": os.environ["DATABASE_NAME"],
            "database_user": os.environ["DATABASE_USER"],
            "database_password": os.environ["DATABASE_PASSWORD"],
            "activation_token_ttl_hours": os.environ["ACTIVATION_TOKEN_TTL_HOURS"],
            "activation_challenge_ttl_minutes": os.environ[
                "ACTIVATION_CHALLENGE_TTL_MINUTES"
            ],
        }
    )
    nombre_base = f"smart_parking_migration_{uuid4().hex}"
    url_prueba = settings.model_copy(update={"database_name": nombre_base}).database_url
    url_admin = settings.model_copy(update={"database_name": "postgres"}).database_url
    engine_admin = create_engine(
        url_admin,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    creada = False
    entorno = os.environ.copy()
    entorno["DATABASE_NAME"] = nombre_base

    def migrar(*argumentos: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "alembic", *argumentos],
            cwd=PROJECT_ROOT,
            env=entorno,
            capture_output=True,
            text=True,
            check=False,
        )

    try:
        with engine_admin.connect() as conexion:
            conexion.execute(text(f'CREATE DATABASE "{nombre_base}"'))
        creada = True

        migracion_previa = migrar("upgrade", "20261002_0002")
        assert migracion_previa.returncode == 0
        engine_prueba = create_engine(url_prueba, pool_pre_ping=True)
        try:
            with engine_prueba.begin() as conexion:
                conexion.execute(
                    text(
                        "INSERT INTO usuarios "
                        "(nombre, apellido_paterno, apellido_materno, correo, "
                        "contrasena_hash, rol, correo_verificado, "
                        "debe_cambiar_contrasena, esta_activo) VALUES "
                        "('Admin', 'Legacy', 'Existing', "
                        "'admin-existing@test.invalid', "
                        "'hash-existente-admin', 'ADMIN', false, true, true), "
                        "('Operador', 'Legacy', 'Existing', "
                        "'operator-existing@test.invalid', "
                        "NULL, 'OPERADOR', false, false, true)"
                    )
                )
                filas_antes = conexion.execute(
                    text(
                        "SELECT correo, contrasena_hash, rol, correo_verificado, "
                        "debe_cambiar_contrasena, esta_activo "
                        "FROM usuarios ORDER BY correo"
                    )
                ).all()

            migracion_nueva = migrar("upgrade", "head")
            assert migracion_nueva.returncode == 0

            with engine_prueba.begin() as conexion:
                filas_despues = conexion.execute(
                    text(
                        "SELECT correo, contrasena_hash, rol, correo_verificado, "
                        "debe_cambiar_contrasena, esta_activo "
                        "FROM usuarios ORDER BY correo"
                    )
                ).all()
                assert filas_despues == filas_antes
                definicion = conexion.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname = "
                        "'ck_usuarios_contrasena_hash_pendiente_activacion'"
                    )
                ).scalar_one()
                assert "ADMIN" in definicion and "OPERADOR" in definicion
                conexion.execute(
                    text(
                        "INSERT INTO usuarios "
                        "(nombre, apellido_paterno, apellido_materno, correo, "
                        "contrasena_hash, rol, correo_verificado, "
                        "debe_cambiar_contrasena, esta_activo) VALUES "
                        "('Admin', 'Pending', 'New', 'admin-pending@test.invalid', "
                        "NULL, 'ADMIN', false, false, true)"
                    )
                )

            downgrade_bloqueado = migrar("downgrade", "20261002_0002")
            assert downgrade_bloqueado.returncode != 0
            assert "No se puede revertir" in downgrade_bloqueado.stderr

            with engine_prueba.begin() as conexion:
                conexion.execute(
                    text(
                        "DELETE FROM usuarios "
                        "WHERE correo = 'admin-pending@test.invalid'"
                    )
                )
            downgrade_limpio = migrar("downgrade", "20261002_0002")
            assert downgrade_limpio.returncode == 0

            with engine_prueba.connect() as conexion:
                version = conexion.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                assert version == "20261002_0002"
                restriccion_anterior = conexion.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname = "
                        "'ck_usuarios_contrasena_hash_operador_pendiente'"
                    )
                ).scalar_one()
                assert "OPERADOR" in restriccion_anterior
                assert "ADMIN" not in restriccion_anterior
        finally:
            engine_prueba.dispose()
    finally:
        if creada:
            with engine_admin.connect() as conexion:
                conexion.execute(
                    text(f'DROP DATABASE IF EXISTS "{nombre_base}" WITH (FORCE)')
                )
        engine_admin.dispose()


__all__ = []
