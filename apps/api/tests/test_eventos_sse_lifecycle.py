"""Pruebas del cierre del iterador SSE al terminar la respuesta ASGI."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from threading import Event, Lock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.sse import ServerSentEvent

import app.api.rutas.eventos as eventos
import main as api_main
from app.api.rutas.eventos import ContextoStreamTiempoReal


def _crear_contexto() -> ContextoStreamTiempoReal:
    contexto = ContextoStreamTiempoReal(
        usuario_id=1,
        rol_usuario="ADMIN",
        token_sesion="token-sintetico-de-prueba",
        lease_id=uuid4(),
        cursor=0,
        marca_inicial=1,
        requiere_resync=True,
    )
    contexto.iterador_eventos = eventos._generar_eventos_tiempo_real(contexto)
    return contexto


def _crear_app(contexto: ContextoStreamTiempoReal) -> FastAPI:
    app = FastAPI()

    def proporcionar_contexto(
        request: Request,
        response: Response,
    ) -> ContextoStreamTiempoReal:
        response.headers.update(eventos.CABECERAS_SSE)
        eventos._registrar_contexto_stream_sse(contexto)
        request.scope[eventos.CLAVE_CONTEXTO_STREAM_SSE] = contexto
        return contexto

    app.dependency_overrides[eventos._preparar_contexto_stream_tiempo_real] = (
        proporcionar_contexto
    )
    app.include_router(eventos.router)
    return app


def _crear_scope(spec_version: str) -> dict[str, object]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": eventos.RUTA_EVENTOS_TIEMPO_REAL,
        "raw_path": eventos.RUTA_EVENTOS_TIEMPO_REAL.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "server": ("testserver", 80),
        "client": ("testclient", 1234),
    }


def test_desconexion_asgi_finaliza_iterador_y_cierra_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexto = _crear_contexto()
    app = _crear_app(contexto)
    cierre_lease = Event()
    cierres_lease: list[int] = []
    candado = Lock()
    iteradores_finalizados: list[object] = []
    original_finalizar = eventos._finalizar_iterador_sse

    def cerrar_lease(_: ContextoStreamTiempoReal) -> None:
        with candado:
            cierres_lease.append(1)
        cierre_lease.set()

    async def observar_finalizacion(iterador: object | None) -> None:
        await original_finalizar(iterador)  # type: ignore[arg-type]
        if iterador is not None:
            iteradores_finalizados.append(iterador)

    monkeypatch.setattr(eventos, "_cerrar_lease_en_sesion", cerrar_lease)
    monkeypatch.setattr(eventos, "_finalizar_iterador_sse", observar_finalizacion)

    async def ejecutar() -> list[dict[str, object]]:
        cuerpo_enviado = asyncio.Event()
        mensajes: list[dict[str, object]] = []

        async def recibir() -> dict[str, object]:
            await cuerpo_enviado.wait()
            return {"type": "http.disconnect"}

        async def enviar(mensaje: dict[str, object]) -> None:
            mensajes.append(mensaje)
            if mensaje["type"] == "http.response.body" and mensaje.get("body"):
                cuerpo_enviado.set()

        await app(_crear_scope("2.3"), recibir, enviar)  # type: ignore[arg-type]
        return mensajes

    mensajes = asyncio.run(ejecutar())

    assert cierre_lease.is_set()
    assert cierres_lease == [1]
    assert contexto.lease_cerrada is True
    assert contexto.iterador_eventos is not None
    assert getattr(contexto.iterador_eventos, "ag_frame", None) is None
    assert len(iteradores_finalizados) >= 2
    assert all(
        getattr(iterador, "ag_frame", None) is None
        for iterador in iteradores_finalizados
    )
    assert any(mensaje["type"] == "http.response.start" for mensaje in mensajes)

    asyncio.run(eventos._finalizar_iterador_sse(contexto.iterador_eventos))
    asyncio.run(eventos._finalizar_iterador_sse(contexto.iterador_eventos))
    assert cierres_lease == [1]


def test_cancelacion_repetida_espera_cierre_y_se_propaga(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexto = _crear_contexto()
    app = _crear_app(contexto)
    cierre_iniciado = Event()
    permitir_cierre = Event()
    cantidad_cierres = 0
    candado = Lock()

    def cerrar_lease(_: ContextoStreamTiempoReal) -> None:
        nonlocal cantidad_cierres
        cierre_iniciado.set()
        permitir_cierre.wait(timeout=2)
        with candado:
            cantidad_cierres += 1

    monkeypatch.setattr(eventos, "_cerrar_lease_en_sesion", cerrar_lease)

    async def ejecutar() -> None:
        cuerpo_iniciado = asyncio.Event()

        async def recibir() -> dict[str, object]:
            await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        async def enviar(mensaje: dict[str, object]) -> None:
            if mensaje["type"] == "http.response.body" and mensaje.get("body"):
                cuerpo_iniciado.set()
                await asyncio.Event().wait()

        tarea = asyncio.create_task(
            app(_crear_scope("2.4"), recibir, enviar)  # type: ignore[arg-type]
        )
        await asyncio.wait_for(cuerpo_iniciado.wait(), timeout=2)
        tarea.cancel()
        assert await asyncio.to_thread(cierre_iniciado.wait, 2)
        tarea.cancel()
        permitir_cierre.set()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    asyncio.run(ejecutar())

    assert cantidad_cierres == 1
    assert contexto.lease_cerrada is True
    assert contexto.iterador_eventos is not None
    assert getattr(contexto.iterador_eventos, "ag_frame", None) is None


def test_desconexion_de_envio_no_se_convierte_en_error_del_servidor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexto = _crear_contexto()
    app = _crear_app(contexto)
    cierres: list[int] = []

    def cerrar_lease(_: ContextoStreamTiempoReal) -> None:
        cierres.append(1)

    monkeypatch.setattr(eventos, "_cerrar_lease_en_sesion", cerrar_lease)

    async def ejecutar() -> list[dict[str, object]]:
        mensajes: list[dict[str, object]] = []

        async def recibir() -> dict[str, object]:
            await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        async def enviar(mensaje: dict[str, object]) -> None:
            mensajes.append(mensaje)
            if mensaje["type"] == "http.response.body" and mensaje.get("body"):
                raise OSError("socket cerrado")

        await app(_crear_scope("2.4"), recibir, enviar)  # type: ignore[arg-type]
        return mensajes

    mensajes = asyncio.run(ejecutar())

    inicio = next(
        mensaje for mensaje in mensajes if mensaje["type"] == "http.response.start"
    )
    assert inicio["status"] == 200
    assert len(cierres) == 1
    assert contexto.lease_cerrada is True


def test_desconexion_antes_del_primer_chunk_cierra_la_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexto = _crear_contexto()
    app = _crear_app(contexto)
    cierres: list[int] = []

    def cerrar_lease(_: ContextoStreamTiempoReal) -> None:
        cierres.append(1)

    monkeypatch.setattr(eventos, "_cerrar_lease_en_sesion", cerrar_lease)

    async def ejecutar() -> None:
        async def recibir() -> dict[str, object]:
            await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        async def enviar(mensaje: dict[str, object]) -> None:
            if mensaje["type"] == "http.response.start":
                raise OSError("socket cerrado antes del body")

        await app(_crear_scope("2.4"), recibir, enviar)  # type: ignore[arg-type]

    asyncio.run(ejecutar())

    assert cierres == [1]
    assert contexto.lease_cerrada is True
    assert contexto.iterador_eventos is not None
    assert getattr(contexto.iterador_eventos, "ag_frame", None) is None


def test_flujo_normal_conserva_el_evento_y_cierra_una_vez(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexto = _crear_contexto()
    app = _crear_app(contexto)
    cierres: list[int] = []
    finalizaciones: list[int] = []

    async def eventos_controlados(
        _: ContextoStreamTiempoReal,
    ) -> AsyncGenerator[ServerSentEvent]:
        try:
            yield ServerSentEvent(
                id="17",
                event="operador.actualizado",
                data={"recurso_tipo": "operador", "recurso_id": 8},
            )
        finally:
            finalizaciones.append(1)

    def cerrar_lease(_: ContextoStreamTiempoReal) -> None:
        cierres.append(1)

    monkeypatch.setattr(eventos, "_cerrar_lease_en_sesion", cerrar_lease)
    contexto.iterador_eventos = eventos_controlados(contexto)

    async def ejecutar() -> list[dict[str, object]]:
        mensajes: list[dict[str, object]] = []

        async def recibir() -> dict[str, object]:
            await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        async def enviar(mensaje: dict[str, object]) -> None:
            mensajes.append(mensaje)

        await app(_crear_scope("2.3"), recibir, enviar)  # type: ignore[arg-type]
        return mensajes

    mensajes = asyncio.run(ejecutar())
    fragmentos: list[bytes] = []
    for mensaje in mensajes:
        cuerpo_evento = mensaje.get("body")
        if mensaje["type"] == "http.response.body" and isinstance(
            cuerpo_evento,
            bytes,
        ):
            fragmentos.append(cuerpo_evento)
    cuerpo = b"".join(fragmentos)

    assert b"event: operador.actualizado" in cuerpo
    assert b"id: 17" in cuerpo
    assert b'data: {"recurso_tipo": "operador", "recurso_id": 8}' in cuerpo
    assert finalizaciones == [1]
    assert cierres == [1]


def test_fallo_de_cierre_se_registra_sin_exponer_detalle(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    contexto = _crear_contexto()
    app = _crear_app(contexto)
    intentos: list[int] = []

    def fallar_cierre(_: ContextoStreamTiempoReal) -> None:
        intentos.append(1)
        raise RuntimeError("detalle interno simulado")

    monkeypatch.setattr(eventos, "_cerrar_lease_en_sesion", fallar_cierre)

    async def ejecutar() -> list[dict[str, object]]:
        cuerpo_enviado = asyncio.Event()
        mensajes: list[dict[str, object]] = []

        async def recibir() -> dict[str, object]:
            await cuerpo_enviado.wait()
            return {"type": "http.disconnect"}

        async def enviar(mensaje: dict[str, object]) -> None:
            mensajes.append(mensaje)
            if mensaje["type"] == "http.response.body" and mensaje.get("body"):
                cuerpo_enviado.set()

        await app(_crear_scope("2.3"), recibir, enviar)  # type: ignore[arg-type]
        return mensajes

    mensajes = asyncio.run(ejecutar())

    inicio = next(
        mensaje for mensaje in mensajes if mensaje["type"] == "http.response.start"
    )
    assert inicio["status"] == 200
    assert len(intentos) == 2
    assert "RuntimeError" in caplog.text
    assert "detalle interno simulado" not in caplog.text


def test_lifespan_cierra_leases_activas_al_apagar_el_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexto = _crear_contexto()
    eventos._registrar_contexto_stream_sse(contexto)
    cierre_lease = Event()
    cierres_lease: list[int] = []
    candado = Lock()

    def cerrar_lease(_: ContextoStreamTiempoReal) -> None:
        with candado:
            cierres_lease.append(1)
        cierre_lease.set()

    monkeypatch.setattr(eventos, "_cerrar_lease_en_sesion", cerrar_lease)
    monkeypatch.setattr(
        api_main,
        "get_settings",
        lambda: SimpleNamespace(correo_transporte="ninguno"),
    )

    async def ejecutar() -> None:
        async with api_main.lifespan(FastAPI()):
            pass

    asyncio.run(ejecutar())
    assert cierre_lease.is_set()
    assert cierres_lease == [1]
    assert contexto.lease_cerrada is True
    assert contexto.lease_id not in eventos._contextos_stream_sse_activos

    asyncio.run(eventos.cerrar_leases_sse_activas())
    assert cierres_lease == [1]
