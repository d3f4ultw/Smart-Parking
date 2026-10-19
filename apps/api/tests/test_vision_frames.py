from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

import app.api.dependencias as dependencias
import app.api.rutas.eventos as rutas_eventos
import app.api.rutas.vision_owner as rutas_vision_owner
import main
from app.core.config import get_settings
from app.core.database import get_db
from app.servicios.vision_frames import (
    MAXIMO_BYTES_FRAME_VISION,
    VisionFrameHub,
    dimensiones_jpeg,
)

JPEG_1X1 = bytes.fromhex("ffd8ffc00011080001000103011100021100031100ffd9")


@pytest.fixture
def vision_frame_client(
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient]:
    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    token = "A" * 43
    settings = get_settings().model_copy(
        update={"vision_bearer_token": SecretStr(token)}
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
            test_client.headers.update({"Authorization": f"Bearer {token}"})
            yield test_client
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        motor.dispose()


def iniciar_sesion_vision(client: TestClient, token: str) -> UUID:
    respuesta = client.post(
        "/api/vision/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert respuesta.status_code == 200
    return UUID(respuesta.json()["session_id"])


def enviar_frame(
    client: TestClient,
    token: str,
    session_id: UUID,
    sequence: int,
    *,
    tipo: str = "annotated",
    jpeg: bytes = JPEG_1X1,
    content_type: str = "image/jpeg",
):
    revision = client.get(
        "/api/vision/configuration",
        headers={"Authorization": f"Bearer {token}"},
    ).json()["revision"]
    return client.post(
        f"/api/vision/frames/{tipo}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
            "X-Vision-Session": str(session_id),
            "X-Vision-Revision": str(revision),
            "X-Vision-Sequence": str(sequence),
        },
        content=jpeg,
    )


def test_frame_ingress_verifica_bearer_sesion_jpeg_y_secuencia(
    vision_frame_client: TestClient,
) -> None:
    token = "A" * 43
    session_id = iniciar_sesion_vision(vision_frame_client, token)
    respuesta = enviar_frame(vision_frame_client, token, session_id, 1)
    assert respuesta.status_code == 202
    assert respuesta.json() == {"accepted": True}
    assert respuesta.headers["cache-control"] == "no-store"
    assert dimensiones_jpeg(JPEG_1X1) == (1, 1)

    repetido = enviar_frame(vision_frame_client, token, session_id, 1)
    assert repetido.status_code == 409

    no_es_jpeg = enviar_frame(
        vision_frame_client,
        token,
        session_id,
        2,
        jpeg=b"not a jpeg",
        content_type="image/png",
    )
    assert no_es_jpeg.status_code == 415

    sesion_vieja = enviar_frame(
        vision_frame_client,
        token,
        uuid4(),
        3,
    )
    assert sesion_vieja.status_code == 409


def test_ingress_rechaza_frame_sobre_limite_de_resolucion(
    vision_frame_client: TestClient,
) -> None:
    token = "A" * 43
    session_id = iniciar_sesion_vision(vision_frame_client, token)
    jpeg_grande = bytearray(JPEG_1X1)
    jpeg_grande[9:11] = (961).to_bytes(2, "big")
    respuesta = enviar_frame(
        vision_frame_client,
        token,
        session_id,
        1,
        jpeg=bytes(jpeg_grande),
    )
    assert respuesta.status_code == 413


def test_ingress_acepta_frame_crudo_720p_bajo_el_limite_actual(
    vision_frame_client: TestClient,
) -> None:
    token = "A" * 43
    session_id = iniciar_sesion_vision(vision_frame_client, token)
    jpeg_720p = bytearray(JPEG_1X1)
    jpeg_720p[7:9] = (720).to_bytes(2, "big")
    jpeg_720p[9:11] = (1280).to_bytes(2, "big")

    respuesta = enviar_frame(
        vision_frame_client,
        token,
        session_id,
        1,
        tipo="raw",
        jpeg=bytes(jpeg_720p),
    )

    assert dimensiones_jpeg(bytes(jpeg_720p)) == (1280, 720)
    assert len(jpeg_720p) <= MAXIMO_BYTES_FRAME_VISION
    assert respuesta.status_code == 202
    assert respuesta.json() == {"accepted": True}


def test_ingress_conserva_el_limite_de_payload_para_frame_crudo(
    vision_frame_client: TestClient,
) -> None:
    token = "A" * 43
    session_id = iniciar_sesion_vision(vision_frame_client, token)
    jpeg_grande = bytearray(JPEG_1X1)
    jpeg_grande[7:9] = (720).to_bytes(2, "big")
    jpeg_grande[9:11] = (1280).to_bytes(2, "big")
    jpeg_grande.extend(b"\x00" * (MAXIMO_BYTES_FRAME_VISION + 1 - len(jpeg_grande)))

    respuesta = enviar_frame(
        vision_frame_client,
        token,
        session_id,
        1,
        tipo="raw",
        jpeg=bytes(jpeg_grande),
    )

    assert respuesta.status_code == 413


def test_ingress_rechaza_frame_sobre_limite_de_pixeles(
    vision_frame_client: TestClient,
) -> None:
    token = "A" * 43
    session_id = iniciar_sesion_vision(vision_frame_client, token)
    jpeg_grande = bytearray(JPEG_1X1)
    jpeg_grande[7:9] = (1200).to_bytes(2, "big")
    jpeg_grande[9:11] = (1800).to_bytes(2, "big")
    respuesta = enviar_frame(
        vision_frame_client,
        token,
        session_id,
        1,
        tipo="raw",
        jpeg=bytes(jpeg_grande),
    )
    assert respuesta.status_code == 413


def test_hub_conserva_un_valor_reciente_y_limita_visualizadores() -> None:
    async def verificar_hub() -> None:
        hub = VisionFrameHub(maximos_visualizadores=4)
        sesion = uuid4()
        await hub.nueva_sesion(sesion)
        assert await hub.publicar_frame(
            "annotated",
            session_id=sesion,
            sequence=2,
            jpeg=JPEG_1X1,
            recibido_en=datetime.now(UTC),
        )
        assert not await hub.publicar_frame(
            "annotated",
            session_id=sesion,
            sequence=1,
            jpeg=JPEG_1X1,
            recibido_en=datetime.now(UTC),
        )
        reservas = []
        for indice in range(4):
            reserva = await hub.reservar_visualizador(
                "raw" if indice == 0 else "annotated"
            )
            assert reserva is not None
            reservas.append(reserva)
        assert not await hub.reservar_visualizador()
        assert await hub.obtener_cantidad_visualizadores() == 4
        activos, liberados = await hub.obtener_detalle_visualizadores()
        assert len(activos) == 4
        assert liberados == []
        assert {detalle.stream_type for detalle in activos} == {"raw", "annotated"}
        for reserva in reservas:
            await reserva.registrar_parte(3, len(JPEG_1X1))
            await reserva.liberar()
            await reserva.liberar()
        assert await hub.obtener_cantidad_visualizadores() == 0
        activos, liberados = await hub.obtener_detalle_visualizadores()
        assert activos == []
        assert len(liberados) == 4
        assert all(detalle.jpeg_parts_emitted == 1 for detalle in liberados)
        assert all(detalle.jpeg_bytes_emitted == len(JPEG_1X1) for detalle in liberados)
        assert all(detalle.last_emitted_sequence == 3 for detalle in liberados)
        assert all(
            detalle.release_reason == "response_complete" for detalle in liberados
        )

        ultimo = await hub.obtener_frame("annotated")
        assert ultimo is not None and ultimo.sequence == 2
        await hub.nueva_sesion(uuid4())
        assert await hub.obtener_frame("annotated") is None
        await hub.cerrar()

    asyncio.run(verificar_hub())


def test_hub_aplica_revision_sin_cerrar_sesion_y_descarta_anotacion_vieja() -> None:
    async def verificar_revision() -> None:
        hub = VisionFrameHub()
        session_id = uuid4()
        await hub.nueva_sesion(session_id, revision=7)
        assert await hub.publicar_frame(
            "raw",
            session_id=session_id,
            revision=7,
            sequence=20,
            jpeg=JPEG_1X1,
            recibido_en=datetime.now(UTC),
        )
        assert await hub.publicar_frame(
            "annotated",
            session_id=session_id,
            revision=7,
            sequence=10,
            jpeg=JPEG_1X1,
            recibido_en=datetime.now(UTC),
        )
        assert await hub.publicar_estado(
            session_id=session_id,
            revision=7,
            sequence=1,
            mode="camera",
            source_connected=True,
            processing=True,
            error_code=None,
            source_fps=24.0,
            inference_fps=10.0,
        )
        lector_raw = await hub.reservar_visualizador("raw")
        lector_anotado = await hub.reservar_visualizador("annotated")
        assert lector_raw is not None and lector_anotado is not None
        activos_antes, liberados_antes = await hub.obtener_detalle_visualizadores()
        ids_reservas = {detalle.diagnostic_id for detalle in activos_antes}
        assert ids_reservas == {lector_raw.diagnostic_id, lector_anotado.diagnostic_id}
        assert liberados_antes == []

        assert await hub.actualizar_revision(8)
        frame_crudo = await hub.obtener_frame("raw")
        assert frame_crudo is not None and frame_crudo.sequence == 20
        assert await hub.obtener_frame("annotated") is None
        estado = await hub.obtener_estado()
        assert estado is not None
        assert estado.session_id == session_id
        assert estado.source_connected and estado.processing
        assert not await hub.publicar_frame(
            "annotated",
            session_id=session_id,
            revision=7,
            sequence=11,
            jpeg=JPEG_1X1,
            recibido_en=datetime.now(UTC),
        )
        assert await hub.publicar_frame(
            "annotated",
            session_id=session_id,
            revision=8,
            sequence=11,
            jpeg=JPEG_1X1,
            recibido_en=datetime.now(UTC),
        )
        assert await hub.obtener_cantidad_visualizadores() == 2
        activos_durante, liberados_durante = await hub.obtener_detalle_visualizadores()
        assert {detalle.diagnostic_id for detalle in activos_durante} == ids_reservas
        assert liberados_durante == []
        frame = await hub.obtener_frame("annotated")
        assert frame is not None and frame.revision == 8
        await lector_raw.registrar_parte(frame_crudo.sequence, len(JPEG_1X1))
        await lector_anotado.registrar_parte(frame.sequence, len(JPEG_1X1))
        await lector_raw.liberar("revision_test_complete")
        await lector_anotado.liberar("revision_test_complete")
        activos_despues, liberados_despues = await hub.obtener_detalle_visualizadores()
        assert activos_despues == []
        assert {detalle.diagnostic_id for detalle in liberados_despues} == ids_reservas
        assert all(detalle.jpeg_parts_emitted == 1 for detalle in liberados_despues)
        await hub.cerrar()

    asyncio.run(verificar_revision())


def test_stream_generator_releases_visualizer_when_client_disconnects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def verificar_cierre() -> None:
        hub = VisionFrameHub()
        session_id = uuid4()
        await hub.nueva_sesion(session_id)
        monkeypatch.setattr(
            rutas_vision_owner,
            "_comprobar_autorizacion_stream",
            lambda _token: True,
        )
        reserva = await hub.reservar_visualizador()
        assert reserva is not None
        stream = rutas_vision_owner._partes_mjpeg(
            hub=hub,
            token_sesion="session-test",
            session_id=session_id,
            tipo="annotated",
            limite=1_048_576,
            boundary="test-boundary",
            reserva=reserva,
        )

        tarea = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.02)
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea
        await stream.aclose()

        assert await hub.obtener_cantidad_visualizadores() == 0
        await reserva.liberar()
        assert await hub.obtener_cantidad_visualizadores() == 0
        await hub.cerrar()

    asyncio.run(verificar_cierre())


def test_stream_route_releases_reservation_if_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def verificar_error_setup() -> None:
        hub = VisionFrameHub()

        async def fallar_estado():
            raise RuntimeError("estado de prueba")

        monkeypatch.setattr(
            rutas_vision_owner, "_obtener_hub", lambda _request: hub
        )
        monkeypatch.setattr(
            rutas_vision_owner,
            "_obtener_token_sesion",
            lambda _request: "session-test",
        )
        monkeypatch.setattr(hub, "obtener_estado", fallar_estado)
        request = Request(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/admin/vision/monitor/stream",
                "raw_path": b"/api/admin/vision/monitor/stream",
                "query_string": b"tipo=annotated",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 80),
                "root_path": "",
            }
        )

        with pytest.raises(RuntimeError, match="estado de prueba"):
            await rutas_vision_owner.transmitir_monitoreo_vision(request)
        assert await hub.obtener_cantidad_visualizadores() == 0
        await hub.cerrar()

    asyncio.run(verificar_error_setup())


def test_stream_response_releases_reservation_when_asgi_send_disconnects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def verificar_desconexion() -> None:
        hub = VisionFrameHub()
        session_id = uuid4()
        await hub.nueva_sesion(session_id)
        await hub.publicar_estado(
            session_id=session_id,
            sequence=1,
            mode="camera",
            source_connected=True,
            processing=True,
            error_code=None,
        )
        await hub.publicar_frame(
            "annotated",
            session_id=session_id,
            sequence=1,
            jpeg=JPEG_1X1,
            recibido_en=datetime.now(UTC),
        )
        monkeypatch.setattr(
            rutas_vision_owner,
            "_obtener_hub",
            lambda _request: hub,
        )
        monkeypatch.setattr(
            rutas_vision_owner,
            "_obtener_token_sesion",
            lambda _request: "session-test",
        )
        monkeypatch.setattr(
            rutas_vision_owner,
            "_comprobar_autorizacion_stream",
            lambda _token: True,
        )
        request = Request(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.4"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/admin/vision/monitor/stream",
                "raw_path": b"/api/admin/vision/monitor/stream",
                "query_string": b"tipo=annotated",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 80),
                "root_path": "",
            }
        )
        response = await rutas_vision_owner.transmitir_monitoreo_vision(request)
        assert await hub.obtener_cantidad_visualizadores() == 1

        async def recibir():
            raise AssertionError("ASGI 2.4 must not poll for http.disconnect")

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.body" and mensaje.get("body"):
                raise OSError("downstream disconnected")

        with pytest.raises(rutas_vision_owner.ClientDisconnect):
            await response(
                request.scope,
                recibir,
                enviar,
            )

        assert await hub.obtener_cantidad_visualizadores() == 0
        activos, liberados = await hub.obtener_detalle_visualizadores()
        assert activos == []
        assert len(liberados) == 1
        assert liberados[0].release_reason == "downstream_disconnect"
        assert liberados[0].jpeg_parts_emitted == 1
        assert liberados[0].last_emitted_sequence == 1
        reserva_reutilizada = await hub.reservar_visualizador("annotated")
        assert reserva_reutilizada is not None
        await reserva_reutilizada.liberar("slot_reuse_test")
        await response.body_iterator.aclose()
        await hub.cerrar()

    asyncio.run(verificar_desconexion())


def test_stream_response_releases_reservation_on_runtime_asgi_23_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def verificar_desconexion() -> None:
        hub = VisionFrameHub()
        session_id = uuid4()
        await hub.nueva_sesion(session_id)
        await hub.publicar_estado(
            session_id=session_id,
            sequence=1,
            mode="camera",
            source_connected=True,
            processing=True,
            error_code=None,
        )
        await hub.publicar_frame(
            "raw",
            session_id=session_id,
            sequence=1,
            jpeg=JPEG_1X1,
            recibido_en=datetime.now(UTC),
        )
        monkeypatch.setattr(
            rutas_vision_owner,
            "_obtener_hub",
            lambda _request: hub,
        )
        monkeypatch.setattr(
            rutas_vision_owner,
            "_obtener_token_sesion",
            lambda _request: "session-test",
        )
        monkeypatch.setattr(
            rutas_vision_owner,
            "_comprobar_autorizacion_stream",
            lambda _token: True,
        )
        request = Request(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/admin/vision/monitor/stream",
                "raw_path": b"/api/admin/vision/monitor/stream",
                "query_string": b"tipo=raw",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 80),
                "root_path": "",
            }
        )
        response = await rutas_vision_owner.transmitir_monitoreo_vision(request)
        primer_frame_enviado = asyncio.Event()
        llamadas_receive = 0

        async def recibir():
            nonlocal llamadas_receive
            llamadas_receive += 1
            if llamadas_receive == 1:
                return {"type": "http.request", "body": b"", "more_body": False}
            await primer_frame_enviado.wait()
            return {"type": "http.disconnect"}

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.body" and mensaje.get("body"):
                primer_frame_enviado.set()

        await response(request.scope, recibir, enviar)

        assert await hub.obtener_cantidad_visualizadores() == 0
        activos, liberados = await hub.obtener_detalle_visualizadores()
        assert activos == []
        assert len(liberados) == 1
        assert liberados[0].stream_type == "raw"
        assert liberados[0].jpeg_parts_emitted == 1
        await hub.cerrar()

    asyncio.run(verificar_desconexion())
