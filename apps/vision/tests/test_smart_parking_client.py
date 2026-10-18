"""Pruebas de contrato local para la publicacion segura de Vision."""

from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4

import pytest

import smart_parking_client as cliente_modulo
from smart_parking_client import (
    INTERVALO_OBSERVACION_SEGUNDOS,
    ConfiguracionRemota,
    SmartParkingClient,
)
from temporal_validation import OccupancyState, ZoneSnapshot


def _snapshot(*, listo: bool) -> tuple[ZoneSnapshot, ...]:
    return (
        ZoneSnapshot(
            identifier="C1",
            polygon=((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)),
            state=OccupancyState.LIBRE,
            missing_valid_frames=0,
            positive_frames_in_window=0,
            is_demo=False,
            is_ready=listo,
        ),
    )


def test_publica_solo_cuando_el_estado_temporal_esta_listo() -> None:
    client = SmartParkingClient("http://localhost:8000", token="v" * 43)
    zone_id = str(uuid4())
    client.configuracion = ConfiguracionRemota(
        revision=4,
        next_c_number=2,
        zones=(
            {
                "vision_zone_id": zone_id,
                "numero": 1,
                "cajon_id": 12,
                "polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
            },
        ),
    )
    client.session_id = uuid4()
    solicitudes: list[dict[str, object]] = []

    def request(_method: str, path: str, body: object | None = None) -> dict[str, object]:
        assert path == "/api/vision/observations"
        assert isinstance(body, dict)
        solicitudes.append(body)
        return {"accepted": True}

    client._request = request  # type: ignore[method-assign]
    assert client.publicar_observaciones(_snapshot(listo=False)) is False
    assert solicitudes == []

    assert client.publicar_observaciones(_snapshot(listo=True)) is True
    assert solicitudes[0]["revision"] == 4
    assert solicitudes[0]["observations"] == [
        {"vision_zone_id": zone_id, "numero": 1, "estado": "LIBRE"}
    ]

    client._ultima_observacion_monotona = (
        time.monotonic() - INTERVALO_OBSERVACION_SEGUNDOS - 1
    )
    assert client.publicar_observaciones(_snapshot(listo=True)) is True
    assert len(solicitudes) == 2


def test_no_publica_si_la_configuracion_canonica_no_tiene_zonas() -> None:
    client = SmartParkingClient("http://localhost:8000", token="v" * 43)
    client.configuracion = ConfiguracionRemota(revision=1, next_c_number=1, zones=())
    client.session_id = uuid4()
    client._request = lambda *_args, **_kwargs: pytest.fail("No debe enviar una lista vacia")  # type: ignore[method-assign]
    assert client.publicar_observaciones(()) is False


def test_cliente_envia_frame_crudo_720p_dentro_del_limite_de_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid4()
    jpeg = bytearray(768 * 1024)
    jpeg[:2] = b"\xff\xd8"
    jpeg[-2:] = b"\xff\xd9"
    solicitudes = []

    class RespuestaAceptada:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limite: int) -> bytes:
            return b'{"accepted":true}'

    def enviar(peticion, *, timeout: float):
        solicitudes.append((peticion, timeout))
        return RespuestaAceptada()

    monkeypatch.setattr(cliente_modulo, "urlopen", enviar)
    client = SmartParkingClient("http://localhost:8000", token="v" * 43)

    client.publicar_frame("raw", session_id, 4, 1, bytes(jpeg))

    assert len(solicitudes) == 1
    peticion, _ = solicitudes[0]
    assert peticion.full_url.endswith("/api/vision/frames/raw")
    assert len(peticion.data) == 768 * 1024
    assert peticion.get_header("Content-type") == "image/jpeg"


def test_la_cache_del_api_reemplaza_cualquier_archivo_local_anterior(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "zones.json"
    destination.write_text(
        json.dumps({"version": 2, "next_c_number": 100, "zones": [{"id": "C99"}]}),
        encoding="utf-8",
    )
    zone_id = str(uuid4())
    client = SmartParkingClient("http://localhost:8000", token="v" * 43)
    client._request = lambda *_args, **_kwargs: {
        "revision": 3,
        "next_c_number": 2,
        "zones": [
            {
                "vision_zone_id": zone_id,
                "numero": 1,
                "cajon_id": 7,
                "polygon": [[0.1, 0.1], [0.8, 0.1], [0.8, 0.8], [0.1, 0.8]],
            }
        ],
    }  # type: ignore[method-assign]
    monkeypatch.setattr(cliente_modulo, "ruta_cache_zonas", lambda: destination)

    configuracion = client.cargar_configuracion()

    assert configuracion.revision == 3
    cache = json.loads(destination.read_text(encoding="utf-8"))
    assert cache["next_c_number"] == 2
    assert cache["zones"] == [
        {
            "id": "C1",
            "vision_zone_id": zone_id,
            "polygon": [[0.1, 0.1], [0.8, 0.1], [0.8, 0.8], [0.1, 0.8]],
        }
    ]


def test_token_ausente_o_corto_falla_sin_incluir_credenciales() -> None:
    with pytest.raises(ValueError) as error:
        SmartParkingClient("http://localhost:8000", token="secreto-corto")
    assert "secreto-corto" not in str(error.value)
    assert "secreto-corto" not in repr(error.value)
