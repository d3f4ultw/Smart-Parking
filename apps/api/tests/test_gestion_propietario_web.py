from __future__ import annotations

import hashlib
import re
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.api.rutas import gestion_propietario as rutas_gestion
from app.api.rutas.gestion_propietario import NOMBRE_COOKIE_GESTION_PROPIETARIO
from app.core.config import Settings
from app.core.database import get_db
from app.correo.mensajes import DatosActivacionCorreo
from app.models import SesionGestionPropietario
from app.servicios.gestion_propietario import (
    CodigoApareamientoInvalido,
    SesionGestionPropietarioNoDisponible,
    emitir_sesion_gestion,
    reclamar_sesion_gestion,
    renovar_sesion_gestion,
    validar_sesion_gestion,
)
from main import app

ORIGEN_GESTION = "http://localhost:3000"


class TransporteFalso:
    """Guarda en memoria un correo sintetico sin exponerlo a otro servicio."""

    def __init__(self) -> None:
        self.mensajes: list[EmailMessage] = []

    def enviar(self, mensaje: DatosActivacionCorreo | EmailMessage) -> None:
        assert isinstance(mensaje, EmailMessage)
        self.mensajes.append(mensaje)


def crear_settings() -> Settings:
    return Settings(
        database_host="localhost",
        database_port=5432,
        database_name="unused",
        database_user="unused",
        database_password=SecretStr("test-only"),
        smtp_host="mailpit",
        smtp_port="1025",
        smtp_from_email="no-reply@example.com",
        smtp_from_name="Smart Parking",
        smtp_security="none",
        app_public_url=ORIGEN_GESTION,
        app_environment="development",
        correo_transporte="smtp",
        session_cookie_name="smart_parking_session",
        session_duration_minutes=480,
        activacion_reenvio_cooldown_segundos=60,
        activation_token_ttl_hours=24,
        activation_challenge_ttl_minutes=15,
    )


@pytest.fixture
def sesiones_concurrentes(database_url: URL) -> Generator[sessionmaker[Session]]:
    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    try:
        yield fabrica
    finally:
        motor.dispose()


@pytest.fixture
def client(database_url: URL) -> Generator[TestClient]:
    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)

    def override_get_db() -> Generator[Session]:
        sesion = fabrica()
        try:
            yield sesion
        finally:
            sesion.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.pop(get_db, None)
        motor.dispose()


def _emitir_y_reclamar(db: Session, instante: datetime):
    emision = emitir_sesion_gestion(db, ahora=instante)
    assert emision.ticket is not None
    assert emision.codigo_apareamiento is not None
    reclamo = reclamar_sesion_gestion(
        db,
        ticket=emision.ticket,
        codigo_apareamiento=emision.codigo_apareamiento,
        credencial_actual=None,
        ahora=instante,
    )
    assert reclamo.credencial_nueva is not None
    return emision, reclamo


def test_credenciales_se_almacenan_solo_como_hashes_y_el_url_se_reutiliza(
    db: Session,
) -> None:
    instante = datetime(2026, 10, 11, 12, tzinfo=UTC)
    emision, reclamo = _emitir_y_reclamar(db, instante)
    assert emision.ticket is not None
    assert emision.codigo_apareamiento is not None
    assert reclamo.credencial_nueva is not None

    registro = db.scalar(select(SesionGestionPropietario))
    assert registro is not None
    assert emision.ticket not in repr(registro)
    assert emision.codigo_apareamiento not in repr(registro)
    assert reclamo.credencial_nueva not in repr(registro)
    assert emision.ticket not in (registro.ticket_hash or "")
    assert emision.codigo_apareamiento not in (registro.codigo_apareamiento_hash or "")
    assert reclamo.credencial_nueva not in (registro.credencial_hash or "")
    assert registro.ticket_hash is not None
    assert registro.codigo_apareamiento_hash is None
    assert registro.credencial_hash is not None

    repetido = reclamar_sesion_gestion(
        db,
        ticket=emision.ticket,
        codigo_apareamiento=None,
        credencial_actual=reclamo.credencial_nueva,
        ahora=instante + timedelta(seconds=20),
    )
    assert repetido.id_sesion == reclamo.id_sesion
    assert repetido.credencial_nueva is None

    with pytest.raises(SesionGestionPropietarioNoDisponible):
        reclamar_sesion_gestion(
            db,
            ticket=emision.ticket,
            codigo_apareamiento=None,
            credencial_actual=None,
            ahora=instante + timedelta(seconds=21),
        )

    emision = emitir_sesion_gestion(db, ahora=instante + timedelta(seconds=22))
    assert emision.estado == "activa"
    assert db.scalar(select(func.count(SesionGestionPropietario.id))) == 1


def test_reemision_reemplaza_ticket_pendiente_y_codigo_incorrecto_no_reclama(
    db: Session,
) -> None:
    instante = datetime(2026, 10, 11, 12, tzinfo=UTC)
    anterior = emitir_sesion_gestion(db, ahora=instante)
    reemplazo = emitir_sesion_gestion(db, ahora=instante + timedelta(seconds=1))
    assert anterior.ticket and anterior.codigo_apareamiento
    assert reemplazo.ticket and reemplazo.codigo_apareamiento
    assert anterior.ticket != reemplazo.ticket

    with pytest.raises(SesionGestionPropietarioNoDisponible):
        reclamar_sesion_gestion(
            db,
            ticket=anterior.ticket,
            codigo_apareamiento=anterior.codigo_apareamiento,
            credencial_actual=None,
            ahora=instante + timedelta(seconds=2),
        )
    with pytest.raises(CodigoApareamientoInvalido):
        reclamar_sesion_gestion(
            db,
            ticket=reemplazo.ticket,
            codigo_apareamiento="A" * 16,
            credencial_actual=None,
            ahora=instante + timedelta(seconds=2),
        )

    sesion = db.scalar(
        select(SesionGestionPropietario).where(
            SesionGestionPropietario.estado == "pendiente"
        )
    )
    assert sesion is not None
    assert sesion.estado == "pendiente"
    assert sesion.intentos_apareamiento == 1


def test_ticket_caduca_despues_de_sesenta_segundos_y_permite_nueva_emision(
    db: Session,
) -> None:
    instante = datetime(2026, 10, 11, 12, tzinfo=UTC)
    emision, reclamo = _emitir_y_reclamar(db, instante)
    assert emision.ticket and reclamo.credencial_nueva

    assert (
        validar_sesion_gestion(
            db,
            credencial=reclamo.credencial_nueva,
            ahora=instante + timedelta(seconds=59),
        )
        == reclamo.id_sesion
    )
    assert not renovar_sesion_gestion(
        db,
        credencial=reclamo.credencial_nueva,
        ahora=instante + timedelta(seconds=60),
    )
    assert (
        validar_sesion_gestion(
            db,
            credencial=reclamo.credencial_nueva,
            ahora=instante + timedelta(seconds=61),
        )
        is None
    )
    with pytest.raises(SesionGestionPropietarioNoDisponible):
        reclamar_sesion_gestion(
            db,
            ticket=emision.ticket,
            codigo_apareamiento=None,
            credencial_actual=reclamo.credencial_nueva,
            ahora=instante + timedelta(seconds=61),
        )

    nueva = emitir_sesion_gestion(db, ahora=instante + timedelta(seconds=62))
    assert nueva.estado == "emitida"
    assert nueva.ticket != emision.ticket


def test_expira_enlace_pendiente_despues_de_su_ventana_corta(db: Session) -> None:
    instante = datetime(2026, 10, 11, 12, tzinfo=UTC)
    emision = emitir_sesion_gestion(db, ahora=instante)
    assert emision.ticket and emision.codigo_apareamiento
    with pytest.raises(SesionGestionPropietarioNoDisponible):
        reclamar_sesion_gestion(
            db,
            ticket=emision.ticket,
            codigo_apareamiento=emision.codigo_apareamiento,
            credencial_actual=None,
            ahora=instante + timedelta(minutes=10),
        )
    registro = db.scalar(select(SesionGestionPropietario))
    assert registro is not None
    assert registro.estado == "expirada"
    assert registro.ticket_hash is None


def test_concurrencia_de_emision_y_claim_deja_un_solo_navegador(
    db: Session,
    sesiones_concurrentes: sessionmaker[Session],
) -> None:
    db.rollback()
    instante = datetime(2026, 10, 11, 12, tzinfo=UTC)
    barrera_emision = Barrier(2)

    def emitir_concurrente():
        with sesiones_concurrentes() as sesion:
            barrera_emision.wait(timeout=5)
            return emitir_sesion_gestion(sesion, ahora=instante)

    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        emisiones = list(ejecutor.map(lambda _valor: emitir_concurrente(), range(2)))
    vigentes = [
        emision
        for emision in emisiones
        if emision.ticket and emision.codigo_apareamiento
    ]
    assert len(vigentes) == 2
    registro_pendiente = db.scalar(
        select(SesionGestionPropietario).where(
            SesionGestionPropietario.estado == "pendiente"
        )
    )
    assert registro_pendiente is not None
    emision_vigente = next(
        emision
        for emision in vigentes
        if hashlib.sha256(f"owner-web-v1:ticket:{emision.ticket}".encode()).hexdigest()
        == registro_pendiente.ticket_hash
    )

    barrera_claim = Barrier(2)

    def reclamar_concurrente():
        with sesiones_concurrentes() as sesion:
            barrera_claim.wait(timeout=5)
            try:
                return reclamar_sesion_gestion(
                    sesion,
                    ticket=emision_vigente.ticket or "",
                    codigo_apareamiento=emision_vigente.codigo_apareamiento,
                    credencial_actual=None,
                    ahora=instante + timedelta(seconds=1),
                )
            except SesionGestionPropietarioNoDisponible:
                return None
            except CodigoApareamientoInvalido:
                return None

    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        reclamos = list(ejecutor.map(lambda _valor: reclamar_concurrente(), range(2)))
    assert sum(reclamo is not None for reclamo in reclamos) == 1

    db.expire_all()
    activas = db.scalars(
        select(SesionGestionPropietario).where(
            SesionGestionPropietario.estado.in_(("pendiente", "activa"))
        )
    ).all()
    assert len(activas) == 1
    assert activas[0].estado == "activa"


def test_api_exige_cookie_dedicada_origen_y_no_expone_rutas_fuera_de_fase_2(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = crear_settings()
    monkeypatch.setattr(rutas_gestion, "get_settings", lambda: settings)
    instante = datetime.now(UTC)
    emision, reclamo = _emitir_y_reclamar(db, instante)
    assert emision.ticket and emision.codigo_apareamiento and reclamo.credencial_nueva

    anonimo = client.get("/api/gestion-propietario/v1/estado")
    assert anonimo.status_code == 401
    assert anonimo.headers["cache-control"] == "no-store"

    no_origen = client.post(
        "/api/gestion-propietario/v1/claim",
        json={"ticket": "x" * 43, "codigo_apareamiento": "A" * 16},
    )
    assert no_origen.status_code == 403

    cookie = f"{NOMBRE_COOKIE_GESTION_PROPIETARIO}={reclamo.credencial_nueva}"
    estado = client.get(
        "/api/gestion-propietario/v1/estado",
        headers={"cookie": cookie},
    )
    assert estado.status_code == 200
    assert estado.json() == {
        "owner_activo": False,
        "owner": None,
        "desvinculacion_segundos_restantes": 0,
        "inscripciones": [],
    }
    assert estado.headers["cache-control"] == "no-store"
    assert NOMBRE_COOKIE_GESTION_PROPIETARIO not in estado.text

    assert client.post("/api/gestion-propietario/v1/salir").status_code == 404
    solicitud_desvinculacion = client.post(
        "/api/gestion-propietario/v1/desvinculacion",
        headers={"origin": ORIGEN_GESTION},
        json={"contrasena_admin": "contrasena-sintetica"},
    )
    assert solicitud_desvinculacion.status_code == 401
    confirmacion_sin_cookie = client.post(
        "/api/gestion-propietario/v1/desvinculacion/confirmar",
        headers={"origin": ORIGEN_GESTION},
        json={"token": "x" * 43},
    )
    assert confirmacion_sin_cookie.status_code == 410
    assert client.get("/api/gestion-propietario/v1/sesion").json() == {"activa": False}


def test_claim_emite_cookie_httponly_y_no_consume_url(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = crear_settings()
    monkeypatch.setattr(rutas_gestion, "get_settings", lambda: settings)
    emision = emitir_sesion_gestion(db)
    assert emision.ticket and emision.codigo_apareamiento

    respuesta = client.post(
        "/api/gestion-propietario/v1/claim",
        headers={"origin": ORIGEN_GESTION},
        json={
            "ticket": emision.ticket,
            "codigo_apareamiento": emision.codigo_apareamiento,
        },
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == {"activa": True}
    cookie = respuesta.headers["set-cookie"]
    assert cookie.startswith(NOMBRE_COOKIE_GESTION_PROPIETARIO + "=")
    assert "httponly" in cookie.casefold()
    assert "samesite=strict" in cookie.casefold()
    assert "path=/" in cookie.casefold()

    repetir = client.post(
        "/api/gestion-propietario/v1/claim",
        headers={"origin": ORIGEN_GESTION},
        json={"ticket": emision.ticket},
    )
    assert repetir.status_code == 200
    assert repetir.headers.get("set-cookie") is None

    otra_sesion = TestClient(app)
    try:
        sin_cookie = otra_sesion.post(
            "/api/gestion-propietario/v1/claim",
            headers={"origin": ORIGEN_GESTION},
            json={"ticket": emision.ticket},
        )
        assert sin_cookie.status_code == 404
    finally:
        otra_sesion.close()


def test_inscripcion_web_envia_solo_por_accion_y_recupera_estado(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = crear_settings()
    transporte = TransporteFalso()
    monkeypatch.setattr(rutas_gestion, "get_settings", lambda: settings)
    monkeypatch.setattr(
        rutas_gestion,
        "crear_transporte_correo",
        lambda _settings: transporte,
    )
    emision = emitir_sesion_gestion(db)
    assert emision.ticket and emision.codigo_apareamiento
    claim = client.post(
        "/api/gestion-propietario/v1/claim",
        headers={"origin": ORIGEN_GESTION},
        json={
            "ticket": emision.ticket,
            "codigo_apareamiento": emision.codigo_apareamiento,
        },
    )
    assert claim.status_code == 200

    correo = f"owner-web-{uuid4().hex}@example.com"
    estado_inicial = client.get("/api/gestion-propietario/v1/estado")
    assert estado_inicial.status_code == 200
    assert estado_inicial.json()["inscripciones"] == []
    assert transporte.mensajes == []

    creada = client.post(
        "/api/gestion-propietario/v1/inscripciones",
        headers={"origin": ORIGEN_GESTION},
        json={"correo": correo},
    )
    assert creada.status_code == 204
    assert len(transporte.mensajes) == 1

    estado = client.get("/api/gestion-propietario/v1/estado").json()
    registro = estado["inscripciones"][0]
    assert registro["correo"] == correo.casefold()
    assert registro["estado"] == "pendiente"
    assert registro["correo_inicial_enviado"] is True
    assert registro["reenviados_usados"] == 0
    assert registro["reenviados_restantes"] == 3
    assert registro["enlace_vigente"] is True
    assert registro["segundos_proceso"] > 0
    assert "token_hash" not in registro
    assert "desafio_hash" not in registro

    segunda_inicial = client.post(
        "/api/gestion-propietario/v1/inscripciones",
        headers={"origin": ORIGEN_GESTION},
        json={"correo": correo},
    )
    assert segunda_inicial.status_code == 409
    assert len(transporte.mensajes) == 1

    correo_distinto = f"owner-web-{uuid4().hex}@example.com"
    alta_con_otro_correo = client.post(
        "/api/gestion-propietario/v1/inscripciones",
        headers={"origin": ORIGEN_GESTION},
        json={"correo": correo_distinto},
    )
    assert alta_con_otro_correo.status_code == 409
    assert len(transporte.mensajes) == 1

    espera = client.post(
        f"/api/gestion-propietario/v1/inscripciones/{registro['id']}/reenviar",
        headers={"origin": ORIGEN_GESTION},
    )
    assert espera.status_code == 429
    assert len(transporte.mensajes) == 1
    assert re.fullmatch(
        r"owner-web-[a-f0-9]+@example\.com",
        estado["inscripciones"][0]["correo"],
    )


def test_ruta_admin_normal_no_acepta_sesion_temporal(
    client: TestClient,
    db: Session,
) -> None:
    _, reclamo = _emitir_y_reclamar(db, datetime.now(UTC))
    assert reclamo.credencial_nueva
    respuesta = client.get(
        "/api/cajones",
        headers={
            "cookie": (
                f"{NOMBRE_COOKIE_GESTION_PROPIETARIO}={reclamo.credencial_nueva}"
            ),
        },
    )
    assert respuesta.status_code == 401
