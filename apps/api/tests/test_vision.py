"""Contratos de configuracion dinamica y telemetria autenticada de Vision."""

from __future__ import annotations

import secrets
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

import app.api.dependencias as dependencias
import app.api.rutas.eventos as rutas_eventos
import main
from app.core.config import get_settings
from app.core.database import get_db
from app.models import Cajon, VisionConfiguration
from app.servicios.vision import obtener_estado_vision

POLIGONO_A = [[0.1, 0.1], [0.4, 0.1], [0.4, 0.4], [0.1, 0.4]]
POLIGONO_B = [[0.6, 0.6], [0.9, 0.6], [0.9, 0.9], [0.6, 0.9]]


@pytest.fixture
def token_vision() -> str:
    return secrets.token_urlsafe(32)


@pytest.fixture
def vision_client(
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
    token_vision: str,
) -> Generator[TestClient]:
    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    settings = get_settings().model_copy(
        update={"vision_bearer_token": SecretStr(token_vision)}
    )

    def entregar_db() -> Generator[Session]:
        db = fabrica()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = entregar_db
    monkeypatch.setattr(dependencias, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(rutas_eventos, "SessionLocal", fabrica)
    try:
        with TestClient(main.app) as test_client:
            yield test_client
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        motor.dispose()


def _reiniciar_zonas(db: Session) -> None:
    db.rollback()
    db.execute(delete(Cajon))
    configuracion = db.get(VisionConfiguration, 1)
    assert configuracion is not None
    configuracion.revision = 0
    configuracion.next_c_number = 1
    configuracion.current_session_id = None
    configuracion.last_heartbeat_at = None
    configuracion.last_observation_at = None
    configuracion.last_sequence = 0
    db.commit()
    db.rollback()


def _crear_zona(
    polygon: list[list[float]], zone_id: str | None = None
) -> dict[str, object]:
    return {
        "vision_zone_id": zone_id or str(uuid4()),
        "numero": None,
        "polygon": polygon,
    }


def _guardar(
    client: TestClient,
    token: str,
    revision: int,
    zones: list[dict[str, object]],
    request_id: str | None = None,
):
    return client.put(
        "/api/vision/configuration",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "request_id": request_id or str(uuid4()),
            "expected_revision": revision,
            "zones": zones,
        },
    )


def test_configuracion_vision_asigna_canonicos_e_idempotencia(
    vision_client: TestClient,
    db: Session,
    token_vision: str,
) -> None:
    _reiniciar_zonas(db)
    sin_token = vision_client.get("/api/vision/configuration")
    assert sin_token.status_code == 401

    encabezados = {"Authorization": f"Bearer {token_vision}"}
    inicial = vision_client.get("/api/vision/configuration", headers=encabezados)
    assert inicial.status_code == 200
    assert inicial.json() == {"revision": 0, "next_c_number": 1, "zones": []}

    request_id = str(uuid4())
    solicitud = [
        _crear_zona(POLIGONO_A),
        _crear_zona(POLIGONO_B),
    ]
    creada = _guardar(vision_client, token_vision, 0, solicitud, request_id)
    assert creada.status_code == 200
    instantanea = creada.json()
    assert [zona["numero"] for zona in instantanea["zones"]] == [1, 2]
    assert all(zona["cajon_id"] > 0 for zona in instantanea["zones"])
    assert len({zona["cajon_id"] for zona in instantanea["zones"]}) == 2
    assert instantanea["next_c_number"] == 3
    assert all(
        zona["polygon"] in (POLIGONO_A, POLIGONO_B) for zona in instantanea["zones"]
    )

    repetida = _guardar(vision_client, token_vision, 0, solicitud, request_id)
    assert repetida.status_code == 200
    assert repetida.json() == instantanea

    idempotencia_conflictiva = _guardar(
        vision_client,
        token_vision,
        0,
        [_crear_zona(POLIGONO_A)],
        request_id,
    )
    assert idempotencia_conflictiva.status_code == 409


def test_vision_fencea_sesion_revision_y_secuencia_y_acepta_snapshot_completo(
    vision_client: TestClient,
    db: Session,
    token_vision: str,
) -> None:
    _reiniciar_zonas(db)
    guardado = _guardar(
        vision_client,
        token_vision,
        0,
        [_crear_zona(POLIGONO_A), _crear_zona(POLIGONO_B)],
    )
    assert guardado.status_code == 200
    configuracion = guardado.json()

    encabezados = {"Authorization": f"Bearer {token_vision}"}
    sesion_anterior = vision_client.post(
        "/api/vision/sessions", headers=encabezados
    ).json()
    sesion_actual = vision_client.post(
        "/api/vision/sessions", headers=encabezados
    ).json()
    heartbeat_anterior = vision_client.post(
        "/api/vision/heartbeat",
        headers=encabezados,
        json={
            "request_id": str(uuid4()),
            "session_id": sesion_anterior["session_id"],
            "sequence": 1,
        },
    )
    assert heartbeat_anterior.status_code == 409

    cuerpo_observaciones = {
        "request_id": str(uuid4()),
        "session_id": sesion_actual["session_id"],
        "revision": configuracion["revision"],
        "sequence": 1,
        "observations": [
            {
                "vision_zone_id": zona["vision_zone_id"],
                "numero": zona["numero"],
                "estado": "OCUPADO" if zona["numero"] == 1 else "LIBRE",
            }
            for zona in configuracion["zones"]
        ],
    }
    observada = vision_client.post(
        "/api/vision/observations",
        headers=encabezados,
        json=cuerpo_observaciones,
    )
    assert observada.status_code == 200
    assert observada.json()["changed_slots"] == 2
    assert (
        vision_client.post(
            "/api/vision/observations",
            headers=encabezados,
            json=cuerpo_observaciones,
        ).json()
        == observada.json()
    )

    con_revision_vieja = {
        **cuerpo_observaciones,
        "request_id": str(uuid4()),
        "revision": 0,
        "sequence": 2,
    }
    assert (
        vision_client.post(
            "/api/vision/observations",
            headers=encabezados,
            json=con_revision_vieja,
        ).status_code
        == 409
    )

    db.expire_all()
    zonas = db.scalars(select(Cajon).order_by(Cajon.numero)).all()
    assert [zona.estado_fisico for zona in zonas] == ["OCUPADO", "LIBRE"]
    assert obtener_estado_vision(db)["stale"] is False
    assert (
        obtener_estado_vision(
            db,
            ahora=datetime.now(UTC) + timedelta(seconds=46),
        )["stale"]
        is True
    )


def test_retirar_zona_no_reutiliza_numero_y_eliminar_toda_configuracion_es_valido(
    vision_client: TestClient,
    db: Session,
    token_vision: str,
) -> None:
    _reiniciar_zonas(db)
    originales = [_crear_zona(POLIGONO_A), _crear_zona(POLIGONO_B)]
    creada = _guardar(vision_client, token_vision, 0, originales)
    assert creada.status_code == 200
    zonas = creada.json()["zones"]

    retirada = _guardar(
        vision_client,
        token_vision,
        1,
        [
            {
                "vision_zone_id": zonas[1]["vision_zone_id"],
                "numero": 2,
                "polygon": [[0.61, 0.6], [0.9, 0.6], [0.9, 0.9], [0.61, 0.9]],
            }
        ],
    )
    assert retirada.status_code == 200
    assert [zona["numero"] for zona in retirada.json()["zones"]] == [2]
    assert retirada.json()["next_c_number"] == 3

    db.expire_all()
    tombstone = db.scalar(select(Cajon).where(Cajon.numero == 1))
    assert tombstone is not None and tombstone.activa is False
    assert str(tombstone.vision_zone_id) == zonas[0]["vision_zone_id"]

    reactivacion = _guardar(
        vision_client,
        token_vision,
        2,
        [
            {
                "vision_zone_id": zonas[0]["vision_zone_id"],
                "numero": 1,
                "polygon": POLIGONO_A,
            }
        ],
    )
    assert reactivacion.status_code == 422

    nueva = _guardar(
        vision_client,
        token_vision,
        2,
        [
            {
                "vision_zone_id": zonas[1]["vision_zone_id"],
                "numero": 2,
                "polygon": [[0.61, 0.6], [0.9, 0.6], [0.9, 0.9], [0.61, 0.9]],
            },
            _crear_zona(POLIGONO_A),
        ],
    )
    assert nueva.status_code == 200
    assert [zona["numero"] for zona in nueva.json()["zones"]] == [2, 3]

    vacia = _guardar(vision_client, token_vision, 3, [])
    assert vacia.status_code == 200
    assert vacia.json()["zones"] == []
    assert vacia.json()["next_c_number"] == 4
