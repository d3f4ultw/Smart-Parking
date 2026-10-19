from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


def test_migracion_reemplaza_vencimiento_por_autorizacion_de_sesion(
    db: Session,
) -> None:
    conexion = db.connection()
    columnas = {
        columna["name"]: columna
        for columna in inspect(conexion).get_columns("sesiones")
    }

    assert "vision_elevada_hasta" not in columnas
    assert columnas["vision_autorizada"]["nullable"] is False
    assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261018_0002"
