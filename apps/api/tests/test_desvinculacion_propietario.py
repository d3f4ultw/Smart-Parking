from __future__ import annotations

import re
import secrets
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from threading import Barrier
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.api.rutas import gestion_propietario as rutas_gestion
from app.api.rutas.eventos import RUTA_EVENTOS_TIEMPO_REAL
from app.api.rutas.gestion_propietario import NOMBRE_COOKIE_GESTION_PROPIETARIO
from app.core.config import Settings
from app.core.database import get_db
from app.correo.errores import ErrorEnvioCorreo
from app.models import (
    CuentaPropietario,
    DesvinculacionPropietario,
    RolUsuario,
    Sesion,
    Usuario,
)
from app.seguridad.contrasenas import crear_hash_contrasena
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.desvinculacion_propietario import (
    ConfirmacionDesvinculacionNoValidaError,
    confirmar_desvinculacion_propietario,
    hash_token_desvinculacion,
    solicitar_desvinculacion_propietario,
)
from app.servicios.gestion_propietario import (
    emitir_sesion_gestion,
    reclamar_sesion_gestion,
    renovar_sesion_gestion,
)
from main import app

ORIGEN = "http://localhost:3000"
CONTRASENA_LOGIN = "Owner Login Pass 123"
CONTRASENA_ADMIN = "Owner Admin Pass 456"


class TransporteCaptura:
    """Conserva en memoria solo los mensajes sinteticos de la prueba."""

    def __init__(self) -> None:
        self.mensajes: list[EmailMessage] = []

    def enviar(self, mensaje: EmailMessage) -> None:
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
        smtp_from_email="no-reply@example.test",
        smtp_from_name="Smart Parking",
        smtp_security="none",
        app_public_url=ORIGEN,
        app_environment="development",
        correo_transporte="smtp",
        session_cookie_name="smart_parking_session",
        session_duration_minutes=480,
        activacion_reenvio_cooldown_segundos=60,
        activation_token_ttl_hours=24,
        activation_challenge_ttl_minutes=15,
    )


@pytest.fixture
def client(database_url: URL) -> Generator[TestClient]:
    """Conecta FastAPI a la base aislada de esta suite."""

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


def crear_owner(
    db: Session,
    *,
    rol_anterior: str | None = None,
) -> tuple[Usuario, CuentaPropietario, str]:
    """Crea una cuenta OWNER sintética y conserva una sesión normal."""

    identificador = uuid4().hex
    token_sesion = secrets.token_urlsafe(32)
    usuario = Usuario(
        nombre="Prueba",
        apellido_paterno="Owner",
        correo=f"owner-unlink-{identificador}@example.test",
        contrasena_hash=crear_hash_contrasena(CONTRASENA_LOGIN),
        rol=RolUsuario.OWNER.value,
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(usuario)
    db.flush()
    cuenta = CuentaPropietario(
        usuario_id=usuario.id,
        contrasena_admin_hash=crear_hash_contrasena(CONTRASENA_ADMIN),
        rol_anterior=rol_anterior,
    )
    db.add(cuenta)
    db.add(
        Sesion(
            usuario_id=usuario.id,
            token_hash=hash_token_sesion(token_sesion),
            expira_en=datetime.now(UTC) + timedelta(hours=8),
            revocado_en=None,
        )
    )
    db.commit()
    return usuario, cuenta, token_sesion


def crear_sesion_gestion(db: Session) -> str:
    emision = emitir_sesion_gestion(db)
    assert emision.ticket is not None
    assert emision.codigo_apareamiento is not None
    reclamo = reclamar_sesion_gestion(
        db,
        ticket=emision.ticket,
        codigo_apareamiento=emision.codigo_apareamiento,
        credencial_actual=None,
    )
    assert reclamo.credencial_nueva is not None
    return reclamo.credencial_nueva


def extraer_token(mensaje: EmailMessage) -> str:
    cuerpo = mensaje.get_body(preferencelist=("plain",))
    assert cuerpo is not None
    enlaces = re.findall(r"https?://[^\s<>\"']+", cuerpo.get_content())
    enlace = next(
        candidato.rstrip(".,;)]}")
        for candidato in enlaces
        if urlsplit(candidato.rstrip(".,;)]}")).path == "/confirmar-desvinculacion"
    )
    partes = urlsplit(enlace)
    assert partes.query == ""
    assert partes.fragment.startswith("desvincular=")
    return partes.fragment.removeprefix("desvincular=")


def test_contrasena_incorrecta_no_envia_correo_y_correcta_permite_confirmar_sin_cookie(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usuario, cuenta, token_sesion = crear_owner(db, rol_anterior=None)
    credencial_gestion = crear_sesion_gestion(db)
    settings = crear_settings()
    transporte = TransporteCaptura()
    monkeypatch.setattr(rutas_gestion, "get_settings", lambda: settings)
    monkeypatch.setattr(
        rutas_gestion,
        "crear_transporte_correo",
        lambda _settings: transporte,
    )
    client.cookies.set(
        NOMBRE_COOKIE_GESTION_PROPIETARIO,
        credencial_gestion,
    )
    ruta = f"{rutas_gestion.RUTA_GESTION_PROPIETARIO}/desvinculacion"
    cabeceras = {"origin": ORIGEN}

    incorrecta = client.post(
        ruta,
        headers=cabeceras,
        json={"contrasena_admin": "incorrecta"},
    )
    assert incorrecta.status_code == 401
    assert incorrecta.json()["detail"] == "La contraseña administrativa no es correcta."
    assert transporte.mensajes == []
    assert db.scalar(select(func.count(DesvinculacionPropietario.id))) == 0

    enviada = client.post(
        ruta,
        headers=cabeceras,
        json={"contrasena_admin": CONTRASENA_ADMIN},
    )
    assert enviada.status_code == 202
    assert enviada.json() == {"estado": "confirmacion_enviada"}
    assert len(transporte.mensajes) == 1
    token = extraer_token(transporte.mensajes[0])
    assert len(token) >= 43

    registro = db.scalar(select(DesvinculacionPropietario))
    assert registro is not None
    assert registro.token_hash == hash_token_desvinculacion(token)
    assert token not in repr(registro)
    assert token not in registro.token_hash
    assert registro.expira_en - registro.emitida_en == timedelta(minutes=15)

    repetida = client.post(
        ruta,
        headers=cabeceras,
        json={"contrasena_admin": CONTRASENA_ADMIN},
    )
    assert repetida.status_code == 409
    assert len(transporte.mensajes) == 1

    # El email puede abrirse en otra instancia sin la cookie de gestion.
    client.cookies.clear()
    confirmacion = client.post(
        f"{rutas_gestion.RUTA_GESTION_PROPIETARIO}/desvinculacion/confirmar",
        headers=cabeceras,
        json={"token": token},
    )
    assert confirmacion.status_code == 200
    assert confirmacion.json() == {"estado": "dueno_desvinculado"}

    db.expire_all()
    usuario_actual = db.get(Usuario, usuario.id)
    cuenta_actual = db.get(CuentaPropietario, cuenta.id)
    assert usuario_actual is not None
    assert cuenta_actual is not None
    assert usuario_actual.rol is None
    assert usuario_actual.esta_activo is True
    assert usuario_actual.correo_verificado is True
    assert usuario_actual.contrasena_hash == usuario.contrasena_hash
    assert cuenta_actual.contrasena_admin_hash is None
    assert cuenta_actual.rol_anterior is None
    sesiones = db.scalars(select(Sesion).where(Sesion.usuario_id == usuario.id)).all()
    assert len(sesiones) == 1
    assert sesiones[0].revocado_en is not None

    replay = client.post(
        f"{rutas_gestion.RUTA_GESTION_PROPIETARIO}/desvinculacion/confirmar",
        headers=cabeceras,
        json={"token": token},
    )
    assert replay.status_code == 410
    assert (
        db.scalar(
            select(func.count(DesvinculacionPropietario.id)).where(
                DesvinculacionPropietario.consumida_en.is_not(None)
            )
        )
        == 1
    )
    assert token not in confirmacion.text
    assert CONTRASENA_ADMIN not in incorrecta.text

    # El lease de gestion sigue activo; el flujo no lo revoca.
    assert renovar_sesion_gestion(db, credencial=credencial_gestion) is True
    client.cookies.set(
        NOMBRE_COOKIE_GESTION_PROPIETARIO,
        credencial_gestion,
    )
    estado = client.get(f"{rutas_gestion.RUTA_GESTION_PROPIETARIO}/estado")
    assert estado.status_code == 200
    assert estado.json()["owner_activo"] is False
    assert estado.json()["owner"] is None

    client.cookies.set("smart_parking_session", token_sesion)
    sesion_caducada = client.get("/api/autenticacion/me")
    assert sesion_caducada.status_code == 401
    client.cookies.clear()


@pytest.mark.parametrize(
    ("rol_anterior", "rol_esperado"),
    [
        ("OPERADOR", "OPERADOR"),
        (None, None),
    ],
)
def test_restaura_rol_previo_o_deja_roleless_sin_deshabilitar_cuenta(
    db: Session,
    rol_anterior: str | None,
    rol_esperado: str | None,
) -> None:
    usuario, cuenta, _ = crear_owner(db, rol_anterior=rol_anterior)
    correo: list[tuple[str, str]] = []
    solicitar_desvinculacion_propietario(
        db,
        contrasena_admin=CONTRASENA_ADMIN,
        entregar_enlace=lambda destino, token: correo.append((destino, token)),
    )
    assert len(correo) == 1
    assert correo[0][0] == usuario.correo

    confirmar_desvinculacion_propietario(db, token=correo[0][1])

    db.expire_all()
    usuario_actual = db.get(Usuario, usuario.id)
    cuenta_actual = db.get(CuentaPropietario, cuenta.id)
    assert usuario_actual is not None
    assert cuenta_actual is not None
    assert usuario_actual.rol == rol_esperado
    assert usuario_actual.esta_activo is True
    assert usuario_actual.contrasena_hash == usuario.contrasena_hash
    assert cuenta_actual.contrasena_admin_hash is None


def test_cuenta_sin_rol_no_inicia_sesion_y_no_accede_a_api_ni_sse(
    db: Session,
    client: TestClient,
) -> None:
    identificador = uuid4().hex
    usuario = Usuario(
        correo=f"owner-roleless-{identificador}@example.com",
        contrasena_hash=crear_hash_contrasena(CONTRASENA_LOGIN),
        rol=None,
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(usuario)
    db.commit()

    login = client.post(
        "/api/autenticacion/login",
        json={
            "correo": usuario.correo,
            "contrasena": CONTRASENA_LOGIN,
        },
    )
    assert login.status_code == 403
    assert login.json()["detail"] == "Esta cuenta no tiene acceso asignado."
    assert "smart_parking_session" not in login.headers.get("set-cookie", "")

    token = secrets.token_urlsafe(32)
    db.add(
        Sesion(
            usuario_id=usuario.id,
            token_hash=hash_token_sesion(token),
            expira_en=datetime.now(UTC) + timedelta(hours=1),
            revocado_en=None,
        )
    )
    db.commit()
    client.cookies.set("smart_parking_session", token)
    assert client.get("/api/autenticacion/me").status_code == 401
    assert client.get("/api/cajones").status_code == 401
    assert client.get(RUTA_EVENTOS_TIEMPO_REAL).status_code == 401
    client.cookies.clear()


def test_enlace_vencido_falsificado_y_reemplazado_no_desvincula(
    db: Session,
) -> None:
    usuario, cuenta, _ = crear_owner(db, rol_anterior="OPERADOR")
    ahora = datetime(2026, 10, 11, 18, tzinfo=UTC)
    tokens: list[str] = []

    solicitar_desvinculacion_propietario(
        db,
        contrasena_admin=CONTRASENA_ADMIN,
        entregar_enlace=lambda _correo, token: tokens.append(token),
        ahora=ahora,
    )
    with pytest.raises(ConfirmacionDesvinculacionNoValidaError):
        confirmar_desvinculacion_propietario(
            db,
            token="x" * 43,
            ahora=ahora + timedelta(minutes=1),
        )
    with pytest.raises(ConfirmacionDesvinculacionNoValidaError):
        confirmar_desvinculacion_propietario(
            db,
            token=tokens[0],
            ahora=ahora + timedelta(minutes=16),
        )

    db.expire_all()
    usuario_actual = db.get(Usuario, usuario.id)
    cuenta_actual = db.get(CuentaPropietario, cuenta.id)
    assert usuario_actual is not None
    assert cuenta_actual is not None
    assert usuario_actual.rol == "OWNER"
    assert cuenta_actual.contrasena_admin_hash is not None

    solicitar_desvinculacion_propietario(
        db,
        contrasena_admin=CONTRASENA_ADMIN,
        entregar_enlace=lambda _correo, token: tokens.append(token),
        ahora=ahora + timedelta(minutes=17),
    )
    assert len(tokens) == 2
    with pytest.raises(ConfirmacionDesvinculacionNoValidaError):
        confirmar_desvinculacion_propietario(
            db,
            token=tokens[0],
            ahora=ahora + timedelta(minutes=18),
        )
    confirmar_desvinculacion_propietario(
        db,
        token=tokens[1],
        ahora=ahora + timedelta(minutes=18),
    )


def test_fallo_smtp_revierte_solicitud_y_conserva_owner_y_sesiones(
    db: Session,
) -> None:
    usuario, cuenta, _ = crear_owner(db)

    def fallar(_correo: str, _token: str) -> None:
        raise ErrorEnvioCorreo

    with pytest.raises(ErrorEnvioCorreo):
        solicitar_desvinculacion_propietario(
            db,
            contrasena_admin=CONTRASENA_ADMIN,
            entregar_enlace=fallar,
        )

    db.expire_all()
    assert db.scalar(select(func.count(DesvinculacionPropietario.id))) == 0
    usuario_actual = db.get(Usuario, usuario.id)
    cuenta_actual = db.get(CuentaPropietario, cuenta.id)
    assert usuario_actual is not None and usuario_actual.rol == "OWNER"
    assert cuenta_actual is not None and cuenta_actual.contrasena_admin_hash is not None
    assert (
        db.scalar(
            select(func.count(Sesion.id)).where(
                Sesion.usuario_id == usuario.id,
                Sesion.revocado_en.is_(None),
            )
        )
        == 1
    )


def test_confirmaciones_concurrentes_aplican_una_sola_transicion(
    db: Session,
    database_url: URL,
) -> None:
    crear_owner(db, rol_anterior=None)
    tokens: list[str] = []
    solicitar_desvinculacion_propietario(
        db,
        contrasena_admin=CONTRASENA_ADMIN,
        entregar_enlace=lambda _correo, token: tokens.append(token),
    )
    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    barrera = Barrier(2)

    def confirmar() -> bool:
        with fabrica() as sesion:
            barrera.wait(timeout=10)
            try:
                confirmar_desvinculacion_propietario(sesion, token=tokens[0])
                return True
            except ConfirmacionDesvinculacionNoValidaError:
                return False

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _indice: confirmar(), range(2)))
    finally:
        motor.dispose()

    assert sum(resultados) == 1
    db.expire_all()
    assert (
        db.scalar(
            select(func.count(DesvinculacionPropietario.id)).where(
                DesvinculacionPropietario.consumida_en.is_not(None)
            )
        )
        == 1
    )
    assert (
        db.scalar(
            select(func.count(Usuario.id)).where(
                Usuario.rol == RolUsuario.OWNER.value,
                Usuario.esta_activo.is_(True),
            )
        )
        == 0
    )
