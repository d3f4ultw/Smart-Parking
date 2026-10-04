from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models import ActivacionCuenta, Sesion, Usuario
from app.seguridad.limitador import limitador_activaciones, limitador_autenticacion

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def estado_rate_limit_aislado() -> Generator[None]:
    """Aísla el estado en memoria del limiter entre pruebas."""

    limitador_activaciones.reiniciar()
    limitador_autenticacion.reiniciar()
    yield
    limitador_activaciones.reiniciar()
    limitador_autenticacion.reiniciar()


@pytest.fixture(scope="session", autouse=True)
def isolated_database() -> Generator[URL]:
    """Crea una base temporal y la migra antes de ejecutar cualquier prueba."""

    source_settings = Settings.model_validate(
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
    temporary_name = f"smart_parking_test_{uuid4().hex}"
    temporary_url = source_settings.model_copy(
        update={"database_name": temporary_name}
    ).database_url
    admin_url = source_settings.model_copy(
        update={"database_name": "postgres"}
    ).database_url
    admin_engine = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    database_created = False
    previous_database_name = os.environ.get("DATABASE_NAME")

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{temporary_name}"'))
        database_created = True

        migration_environment = os.environ.copy()
        migration_environment["DATABASE_NAME"] = temporary_name
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=PROJECT_ROOT,
            env=migration_environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if migration.returncode != 0:
            pytest.fail("No fue posible aplicar Alembic a la base temporal")

        os.environ["DATABASE_NAME"] = temporary_name
        yield temporary_url
    finally:
        if previous_database_name is None:
            os.environ.pop("DATABASE_NAME", None)
        else:
            os.environ["DATABASE_NAME"] = previous_database_name
        if database_created:
            with admin_engine.connect() as connection:
                connection.execute(
                    text(f'DROP DATABASE IF EXISTS "{temporary_name}" WITH (FORCE)')
                )
        admin_engine.dispose()


@pytest.fixture(scope="session")
def database_url(isolated_database: URL) -> URL:
    """Devuelve el objeto URL de la base temporal usada por toda la suite."""

    return isolated_database


@pytest.fixture
def db(database_url: URL) -> Generator[Session]:
    """Entrega una sesion aislada y limpia todas las tablas al terminar."""

    engine = create_engine(database_url, pool_pre_ping=True)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(delete(Sesion))
        session.execute(delete(ActivacionCuenta))
        session.execute(delete(Usuario))
        session.commit()
        session.close()
        engine.dispose()
