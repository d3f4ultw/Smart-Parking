"""Pruebas adversariales de autenticacion para SP-015."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ActivacionCuenta
from app.servicios.activaciones import (
    ActivacionPendienteExistenteError,
    crear_activacion,
)
from app.servicios.usuarios import crear_admin


def correo_de_prueba() -> str:
    return f"sp015-test-{uuid4().hex}@example.com"


def test_generacion_concurrente_solo_deja_una_activacion_pendiente(
    db: Session,
) -> None:
    """La generacion simultanea no debe crear dos credenciales utilizables."""

    usuario = crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo_de_prueba(),
        contrasena="Contrasena segura SP015 123",
        confirmacion_contrasena="Contrasena segura SP015 123",
    ).usuario
    usuario_id = usuario.id
    db.rollback()

    engine = db.get_bind()
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    barrera = Barrier(2)
    ahora = datetime(2026, 9, 27, 18, 0, tzinfo=UTC)

    def intentar_generacion() -> bool:
        sesion = session_factory()
        try:
            barrera.wait()
            crear_activacion(sesion, usuario_id, ahora=ahora)
            return True
        except ActivacionPendienteExistenteError:
            return False
        finally:
            sesion.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        resultados = list(executor.map(lambda _indice: intentar_generacion(), range(2)))

    db.rollback()
    pendientes = db.scalar(
        select(func.count())
        .select_from(ActivacionCuenta)
        .where(
            ActivacionCuenta.usuario_id == usuario_id,
            ActivacionCuenta.consumido_en.is_(None),
        )
    )

    assert sorted(resultados) == [False, True]
    assert pendientes == 1
