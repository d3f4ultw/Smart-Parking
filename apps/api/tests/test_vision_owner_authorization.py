from __future__ import annotations

import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

import app.api.dependencias as dependencias
import app.api.rutas.autenticacion as rutas_autenticacion
import app.api.rutas.eventos as rutas_eventos
import app.api.rutas.vision_owner as rutas_vision_owner
import main
from app.core.config import get_settings
from app.core.database import get_db
from app.models import CuentaPropietario, RolUsuario, Sesion, Usuario
from app.seguridad.contrasenas import crear_hash_contrasena
from app.servicios.autorizacion_vision import sesion_tiene_autorizacion_vision

CONTRASENA_LOGIN = "VisionOwnerLogin-Test-2026!"
CONTRASENA_ADMIN = "VisionOwnerAdmin-Test-2026!"
ORIGEN_WEB = "http://localhost:3301"


@pytest.fixture
def owner_client(
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient]:
    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    settings = get_settings().model_copy(
        update={
            "app_public_url": ORIGEN_WEB,
            "vision_bearer_token": SecretStr("A" * 43),
        }
    )

    def entregar_db() -> Generator[Session]:
        db = fabrica()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = entregar_db
    monkeypatch.setattr(dependencias, "get_settings", lambda: settings)
    monkeypatch.setattr(rutas_autenticacion, "get_settings", lambda: settings)
    monkeypatch.setattr(rutas_vision_owner, "get_settings", lambda: settings)
    monkeypatch.setattr(rutas_vision_owner, "SessionLocal", fabrica)
    monkeypatch.setattr(rutas_eventos, "SessionLocal", fabrica)
    try:
        with TestClient(main.app) as test_client:
            yield test_client
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        motor.dispose()


def crear_owner(db: Session) -> int:
    usuario = Usuario(
        nombre="Vision",
        apellido_paterno="Owner",
        correo=f"vision-owner-{uuid4().hex}@example.com",
        contrasena_hash=crear_hash_contrasena(CONTRASENA_LOGIN),
        rol=RolUsuario.OWNER.value,
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(usuario)
    db.flush()
    db.add(
        CuentaPropietario(
            usuario_id=usuario.id,
            contrasena_admin_hash=crear_hash_contrasena(CONTRASENA_ADMIN),
        )
    )
    db.commit()
    return usuario.id


def iniciar_sesion_owner(client: TestClient, correo: str) -> None:
    respuesta = client.post(
        "/api/autenticacion/login",
        json={"correo": correo, "contrasena": CONTRASENA_LOGIN},
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "credenciales_validas", "rol": "OWNER"}


def verificar(client: TestClient, contrasena: str, *, origen: str = ORIGEN_WEB):
    return client.post(
        "/api/admin/vision/authorization",
        headers={"Origin": origen},
        json={"contrasena_admin": contrasena},
    )


def test_snapshot_rechaza_frames_ausentes_aunque_haya_imagen_de_referencia(
    owner_client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    usuario_id = crear_owner(db)
    correo = db.get(Usuario, usuario_id).correo
    assert correo is not None
    iniciar_sesion_owner(owner_client, correo)
    assert verificar(owner_client, CONTRASENA_ADMIN).status_code == 200

    referencia = tmp_path / "referencia.png"
    referencia.write_bytes(
        bytes(
            (
                137,
                80,
                78,
                71,
                13,
                10,
                26,
                10,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                1,
                0,
                0,
                0,
                1,
            )
        )
    )
    settings = get_settings().model_copy(
        update={"vision_reference_frame_path": referencia}
    )
    monkeypatch.setattr(rutas_vision_owner, "get_settings", lambda: settings)

    respuesta = owner_client.get("/api/admin/vision/monitor/snapshot")

    assert respuesta.status_code == 503
    assert "X-Vision-Snapshot-Source" not in respuesta.headers


def test_monitor_no_publica_libre_cuando_la_fuente_esta_desconectada(
    owner_client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    usuario_id = crear_owner(db)
    correo = db.get(Usuario, usuario_id).correo
    assert correo is not None
    iniciar_sesion_owner(owner_client, correo)
    assert verificar(owner_client, CONTRASENA_ADMIN).status_code == 200

    class HubPrueba:
        async def obtener_cantidad_visualizadores(self) -> int:
            return 0

        async def obtener_detalle_visualizadores(self):
            return [], []

        async def obtener_frame(self, _tipo: str):
            return None

        async def obtener_estado(self):
            return SimpleNamespace(
                session_id=uuid4(),
                sequence=3,
                mode="camera",
                source_connected=False,
                processing=False,
                error_code="SOURCE_UNAVAILABLE",
                actualizado_monotono=time.monotonic(),
                source_fps=0.0,
                inference_fps=0.0,
                zone_states=((1, "LIBRE"),),
            )

    monkeypatch.setattr(
        rutas_vision_owner,
        "_obtener_hub",
        lambda _request: HubPrueba(),
    )

    respuesta = owner_client.get("/api/admin/vision/monitor/status")

    assert respuesta.status_code == 200
    assert respuesta.json()["source_connected"] is False
    assert respuesta.json()["zone_states"] == []
    assert respuesta.json()["error_code"] == "SOURCE_UNAVAILABLE"
    assert respuesta.json()["active_viewers"] == 0
    assert respuesta.json()["active_viewer_details"] == []
    assert respuesta.json()["recent_viewer_releases"] == []


def test_stream_mjpeg_se_reconecta_a_la_sesion_vision_actual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from app.servicios.vision_frames import VisionFrameHub

    monkeypatch.setattr(
        rutas_vision_owner,
        "_comprobar_autorizacion_stream",
        lambda _token: True,
    )

    async def verificar() -> None:
        hub = VisionFrameHub()
        sesion_inicial = uuid4()
        sesion_nueva = uuid4()
        jpeg = bytes(
            (
                255,
                216,
                255,
                192,
                0,
                17,
                8,
                0,
                1,
                0,
                1,
                3,
                1,
                17,
                0,
                2,
                17,
                0,
                3,
                17,
                0,
                255,
                217,
            )
        )
        await hub.nueva_sesion(sesion_inicial)
        await hub.publicar_estado(
            session_id=sesion_inicial,
            sequence=1,
            mode="camera",
            source_connected=True,
            processing=True,
            error_code=None,
        )
        await hub.publicar_frame(
            "annotated",
            session_id=sesion_inicial,
            sequence=1,
            jpeg=jpeg,
            recibido_en=datetime.now(UTC),
        )
        reserva = await hub.reservar_visualizador()
        assert reserva is not None
        flujo = rutas_vision_owner._partes_mjpeg(
            hub=hub,
            token_sesion="session-token-test",
            session_id=sesion_inicial,
            tipo="annotated",
            limite=1_048_576,
            boundary="test-boundary",
            reserva=reserva,
        )

        primer_frame = await asyncio.wait_for(anext(flujo), timeout=1.0)
        assert b"Content-Type: image/jpeg" in primer_frame

        await hub.nueva_sesion(sesion_nueva)
        await hub.publicar_estado(
            session_id=sesion_nueva,
            sequence=1,
            mode="camera",
            source_connected=True,
            processing=True,
            error_code=None,
        )
        await hub.publicar_frame(
            "annotated",
            session_id=sesion_nueva,
            sequence=1,
            jpeg=jpeg,
            recibido_en=datetime.now(UTC),
        )
        siguiente_frame = await asyncio.wait_for(anext(flujo), timeout=1.0)
        assert b"Content-Type: image/jpeg" in siguiente_frame

        await flujo.aclose()
        await hub.cerrar()

    asyncio.run(verificar())


def test_owner_requiere_clave_administrativa_y_la_autorizacion_es_de_sesion(
    owner_client: TestClient,
    db: Session,
) -> None:
    usuario_id = crear_owner(db)
    correo = db.get(Usuario, usuario_id).correo
    assert correo is not None
    assert owner_client.get("/api/admin/vision/authorization").status_code == 401

    iniciar_sesion_owner(owner_client, correo)
    estado_inicial = owner_client.get("/api/admin/vision/authorization")
    assert estado_inicial.status_code == 200
    assert estado_inicial.json() == {"authorized": False}

    sin_origen = verificar(owner_client, CONTRASENA_ADMIN, origen="https://evil.test")
    assert sin_origen.status_code == 403
    clave_login = verificar(owner_client, CONTRASENA_LOGIN)
    assert clave_login.status_code == 401
    assert clave_login.json() == {"detail": "Credenciales administrativas invalidas"}

    autorizada = verificar(owner_client, CONTRASENA_ADMIN)
    assert autorizada.status_code == 200
    assert autorizada.json() == {"authorized": True}
    assert "contrasena" not in autorizada.text.lower()

    token_sesion = owner_client.cookies.get(get_settings().session_cookie_name)
    assert token_sesion is not None
    sesion = db.scalar(select(Sesion).where(Sesion.usuario_id == usuario_id))
    assert sesion is not None
    sesion.expira_en = datetime.now(UTC) + timedelta(hours=1)
    db.commit()
    assert sesion.vision_autorizada is True
    assert (
        sesion_tiene_autorizacion_vision(
            db,
            token_sesion=token_sesion,
            ahora=datetime.now(UTC) + timedelta(minutes=11),
        )
        is True
    )

    configuracion = owner_client.get("/api/admin/vision/configuration")
    assert configuracion.status_code == 200
    assert "zones" in configuracion.json()

    revocada = owner_client.delete(
        "/api/admin/vision/authorization",
        headers={"Origin": ORIGEN_WEB},
    )
    assert revocada.status_code == 200
    assert revocada.json() == {"authorized": False}
    db.refresh(sesion)
    assert sesion.vision_autorizada is False
    assert owner_client.get("/api/admin/vision/configuration").status_code == 403


def test_expiracion_normal_de_sesion_invalida_autorizacion_vision(
    owner_client: TestClient,
    db: Session,
) -> None:
    usuario_id = crear_owner(db)
    correo = db.get(Usuario, usuario_id).correo
    iniciar_sesion_owner(owner_client, correo)
    assert verificar(owner_client, CONTRASENA_ADMIN).status_code == 200

    sesion = db.scalar(select(Sesion).where(Sesion.usuario_id == usuario_id))
    assert sesion is not None
    sesion.expira_en = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert owner_client.get("/api/admin/vision/authorization").status_code == 401
    assert owner_client.get("/api/admin/vision/configuration").status_code == 401


def test_logout_revoca_autorizacion_y_sesion_vision(
    owner_client: TestClient,
    db: Session,
) -> None:
    usuario_id = crear_owner(db)
    correo = db.get(Usuario, usuario_id).correo
    iniciar_sesion_owner(owner_client, correo)
    assert verificar(owner_client, CONTRASENA_ADMIN).status_code == 200

    respuesta = owner_client.post("/api/autenticacion/logout")
    assert respuesta.status_code == 200
    sesion = db.scalar(select(Sesion).where(Sesion.usuario_id == usuario_id))
    assert sesion is not None
    db.refresh(sesion)
    assert sesion.revocado_en is not None
    assert sesion.vision_autorizada is False
    assert owner_client.get("/api/admin/vision/configuration").status_code == 401


def test_contrasena_admin_cambiada_revoca_autorizacion_vision(
    owner_client: TestClient,
    db: Session,
) -> None:
    from app.servicios.autenticacion import revocar_sesiones_usuario

    usuario_id = crear_owner(db)
    correo = db.get(Usuario, usuario_id).correo
    iniciar_sesion_owner(owner_client, correo)
    assert verificar(owner_client, CONTRASENA_ADMIN).status_code == 200

    cuenta = db.scalar(
        select(CuentaPropietario).where(CuentaPropietario.usuario_id == usuario_id)
    )
    assert cuenta is not None
    cuenta.contrasena_admin_hash = crear_hash_contrasena("VisionAdminReplacement-2026!")
    revocar_sesiones_usuario(db, usuario_id=usuario_id)
    db.commit()

    sesion = db.scalar(select(Sesion).where(Sesion.usuario_id == usuario_id))
    assert sesion is not None
    db.refresh(sesion)
    assert sesion.vision_autorizada is False
    assert owner_client.get("/api/admin/vision/configuration").status_code == 401


@pytest.mark.parametrize("revocar_sesion", [False, True])
def test_stream_abierto_se_cierra_al_revocar_sesion_o_autorizacion(
    owner_client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    revocar_sesion: bool,
) -> None:
    from types import SimpleNamespace

    from app.servicios.autenticacion import revocar_sesion_actual

    class HubPrueba:
        released = False

        class ReservaPrueba:
            def __init__(self, hub: HubPrueba) -> None:
                self.hub = hub

            async def liberar(self, _motivo: str = "response_complete") -> None:
                self.hub.released = True

        async def reservar_visualizador(
            self, _tipo: str = "annotated"
        ) -> ReservaPrueba:
            return self.ReservaPrueba(self)

        async def obtener_estado(self) -> SimpleNamespace:
            return SimpleNamespace(session_id=uuid4())

    usuario_id = crear_owner(db)
    correo = db.get(Usuario, usuario_id).correo
    iniciar_sesion_owner(owner_client, correo)
    assert verificar(owner_client, CONTRASENA_ADMIN).status_code == 200
    token_sesion = owner_client.cookies.get(get_settings().session_cookie_name)
    assert token_sesion is not None
    hub = HubPrueba()
    monkeypatch.setattr(rutas_vision_owner, "_obtener_hub", lambda _: hub)

    comprobar_original = rutas_vision_owner._comprobar_autorizacion_stream

    def revocar_antes_de_comprobar(token: str) -> bool:
        with rutas_vision_owner.SessionLocal() as sesion_db:
            if revocar_sesion:
                revocar_sesion_actual(sesion_db, token=token)
            else:
                rutas_vision_owner.revocar_autorizacion_vision_sesion(
                    sesion_db,
                    usuario_id=usuario_id,
                    token_sesion=token,
                )
        return comprobar_original(token)

    monkeypatch.setattr(
        rutas_vision_owner,
        "_comprobar_autorizacion_stream",
        revocar_antes_de_comprobar,
    )
    respuesta = owner_client.get("/api/admin/vision/monitor/stream?tipo=raw")

    assert respuesta.status_code == 200
    assert respuesta.content == b""
    assert hub.released is True
    assert sesion_tiene_autorizacion_vision(db, token_sesion=token_sesion) is False


def test_operador_no_puede_elevarse_a_vision(
    owner_client: TestClient,
    db: Session,
) -> None:
    operador = Usuario(
        correo=f"vision-operador-{uuid4().hex}@example.com",
        contrasena_hash=crear_hash_contrasena(CONTRASENA_LOGIN),
        rol=RolUsuario.OPERADOR.value,
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(operador)
    db.commit()
    respuesta = owner_client.post(
        "/api/autenticacion/login",
        json={"correo": operador.correo, "contrasena": CONTRASENA_LOGIN},
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["rol"] == "OPERADOR"
    assert owner_client.get("/api/admin/vision/authorization").status_code == 403


def test_intentos_de_clave_administrativa_estan_limitados(
    owner_client: TestClient,
    db: Session,
) -> None:
    crear_owner(db)
    correo = db.scalar(select(Usuario.correo).where(Usuario.rol == "OWNER"))
    assert correo is not None
    iniciar_sesion_owner(owner_client, correo)
    for _ in range(5):
        assert verificar(owner_client, "IncorrectVisionAdmin-2026!").status_code == 401
    assert verificar(owner_client, "IncorrectVisionAdmin-2026!").status_code == 429
