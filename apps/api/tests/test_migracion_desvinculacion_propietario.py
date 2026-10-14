from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models import (
    CuentaPropietario,
    DesvinculacionPropietario,
    RolUsuario,
    Usuario,
)
from app.seguridad.contrasenas import crear_hash_contrasena

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION_HEAD = "20261013_0001"
REVISION_PREVIA = "20261011_0004"


def ejecutar_alembic(*argumentos: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *argumentos],
        cwd=PROJECT_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )


def crear_usuario(
    db: Session,
    *,
    rol: str | None,
) -> Usuario:
    usuario = Usuario(
        correo=f"migration-owner-{uuid4().hex}@example.test",
        contrasena_hash=crear_hash_contrasena("Migration Owner Pass 123"),
        rol=rol,
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(usuario)
    db.flush()
    return usuario


def test_migracion_anade_tabla_indices_y_columnas_nullable(db: Session) -> None:
    inspector = inspect(db.get_bind())
    columnas_usuario = {
        columna["name"]: columna for columna in inspector.get_columns("usuarios")
    }
    columnas_cuenta = {
        columna["name"]: columna
        for columna in inspector.get_columns("cuentas_propietario")
    }
    columnas_desvinculacion = {
        columna["name"]: columna
        for columna in inspector.get_columns("desvinculaciones_propietario")
    }
    indices = {
        indice["name"]: indice
        for indice in inspector.get_indexes("desvinculaciones_propietario")
    }

    assert columnas_usuario["rol"]["nullable"] is True
    assert columnas_cuenta["contrasena_admin_hash"]["nullable"] is True
    assert {
        "usuario_id",
        "cuenta_propietario_id",
        "token_hash",
        "emitida_en",
        "expira_en",
        "consumida_en",
        "invalidada_en",
    } <= set(columnas_desvinculacion)
    assert indices["uq_desvinculaciones_propietario_token_hash"]["unique"] is True
    assert indices["uq_desvinculaciones_propietario_pendiente"]["unique"] is True
    opciones = (
        indices["uq_desvinculaciones_propietario_pendiente"].get("dialect_options")
        or {}
    )
    predicado = str(opciones.get("postgresql_where", ""))
    assert (
        "consumida_en is null and invalidada_en is null"
        in predicado.lower().replace("(", "").replace(")", "")
    )


def test_downgrade_vacio_es_seguro_y_se_puede_actualizar_de_nuevo(
    db: Session,
) -> None:
    bajada = ejecutar_alembic("downgrade", REVISION_PREVIA)
    assert bajada.returncode == 0, "El downgrade vacío no terminó correctamente."

    inspector = inspect(db.get_bind())
    tablas = set(inspector.get_table_names())
    columnas_usuario = {
        columna["name"]: columna for columna in inspector.get_columns("usuarios")
    }
    columnas_cuenta = {
        columna["name"]: columna
        for columna in inspector.get_columns("cuentas_propietario")
    }
    assert "desvinculaciones_propietario" not in tablas
    assert columnas_usuario["rol"]["nullable"] is False
    assert columnas_cuenta["contrasena_admin_hash"]["nullable"] is False

    subida = ejecutar_alembic("upgrade", "head")
    assert subida.returncode == 0, "No se pudo volver a aplicar la migración."


@pytest.mark.parametrize("estado_inseguro", ["roleless", "hash_null", "historial"])
def test_downgrade_rechaza_datos_que_no_puede_restaurar(
    db: Session,
    estado_inseguro: str,
) -> None:
    usuario = crear_usuario(
        db,
        rol=None if estado_inseguro == "roleless" else RolUsuario.OWNER.value,
    )
    cuenta: CuentaPropietario | None = None
    if estado_inseguro != "roleless":
        cuenta = CuentaPropietario(
            usuario_id=usuario.id,
            contrasena_admin_hash=(
                None if estado_inseguro == "hash_null" else "hash-admin-valido"
            ),
            rol_anterior=None,
        )
        db.add(cuenta)
        db.flush()
    if estado_inseguro == "historial":
        assert cuenta is not None
        ahora = datetime.now(UTC)
        db.add(
            DesvinculacionPropietario(
                usuario_id=usuario.id,
                cuenta_propietario_id=cuenta.id,
                token_hash="a" * 64,
                emitida_en=ahora,
                expira_en=ahora + timedelta(minutes=15),
            )
        )
    db.commit()

    bajada = ejecutar_alembic("downgrade", REVISION_PREVIA)
    assert bajada.returncode != 0
    assert "No se puede revertir OWNER unlinking" in bajada.stderr

    estado = ejecutar_alembic("current")
    assert estado.returncode == 0
    assert REVISION_HEAD in estado.stdout
