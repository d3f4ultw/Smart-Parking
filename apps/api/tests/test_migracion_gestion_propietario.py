from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.models import SesionGestionPropietario


def test_migracion_crea_tabla_y_unicidad_global_de_sesion(
    db: Session,
) -> None:
    inspector = inspect(db.get_bind())
    columnas = {
        columna["name"]
        for columna in inspector.get_columns("sesiones_gestion_propietario")
    }
    indices = {
        indice["name"]: indice
        for indice in inspector.get_indexes("sesiones_gestion_propietario")
    }

    assert {
        "estado",
        "ticket_hash",
        "codigo_apareamiento_hash",
        "credencial_hash",
        "ultimo_latido_en",
        "preclaim_expira_en",
    } <= columnas
    assert "uq_sesiones_gestion_propietario_activa" in indices
    assert indices["uq_sesiones_gestion_propietario_activa"]["unique"] is True
    assert db.scalar(select(SesionGestionPropietario.id)) is None
