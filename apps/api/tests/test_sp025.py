"""Regresiones SP-025: creacion autenticada de cuentas OPERADOR."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from solicitud_cliente import solicitar_con_cookies
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.database import get_db
from app.models import ActivacionCuenta, RolUsuario, Sesion, Usuario
from app.seguridad.contrasenas import crear_hash_contrasena
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.usuarios import crear_admin
from main import app

RUTA_CREAR_OPERADOR = "/api/admin/operadores"
NOMBRE_COOKIE = "smart_parking_session"
CONTRASENA_ADMIN = "Contrasena segura SP025 123"


def correo_de_prueba() -> str:
    return f"sp025-test-{uuid4().hex}@example.com"


def crear_admin_autenticado(db: Session) -> tuple[Usuario, str]:
    """Crea un ADMIN vigente y una cookie de sesión persistida para la prueba."""

    resultado = crear_admin(
        db,
        nombre="Katherine",
        apellido_paterno="Johnson",
        apellido_materno="Coleman",
        correo=correo_de_prueba(),
        contrasena=CONTRASENA_ADMIN,
        confirmacion_contrasena=CONTRASENA_ADMIN,
    )
    usuario = resultado.usuario
    usuario.esta_activo = True
    usuario.correo_verificado = True
    usuario.debe_cambiar_contrasena = False
    db.commit()
    db.rollback()
    return usuario, crear_sesion(db, usuario)


def crear_sesion(db: Session, usuario: Usuario) -> str:
    token = f"token-sp025-{uuid4().hex}"
    ahora = datetime.now(UTC)
    db.add(
        Sesion(
            usuario_id=usuario.id,
            token_hash=hash_token_sesion(token),
            expira_en=ahora + timedelta(minutes=30),
            revocado_en=None,
            creado_en=ahora,
        )
    )
    db.commit()
    db.rollback()
    return token


def crear_operador_existente(db: Session, correo: str) -> Usuario:
    usuario = Usuario(
        nombre="Grace",
        apellido_paterno="Hopper",
        apellido_materno="Murray",
        correo=correo,
        contrasena_hash=crear_hash_contrasena(CONTRASENA_ADMIN),
        rol=RolUsuario.OPERADOR.value,
        correo_verificado=True,
        esta_activo=True,
        debe_cambiar_contrasena=False,
    )
    db.add(usuario)
    db.commit()
    db.rollback()
    return usuario


@pytest.fixture
def client(database_url: URL) -> Generator[TestClient]:
    """Expone la API con conexiones independientes a la base temporal."""

    test_engine = create_engine(database_url, pool_pre_ping=True)
    fabrica_sesiones = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[Session]:
        db = fabrica_sesiones()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        test_engine.dispose()


def datos_operador(correo: str | None = None) -> dict[str, object]:
    return {
        "nombre": "Grace",
        "apellido_paterno": "Hopper",
        "apellido_materno": "Murray",
        "correo": correo or correo_de_prueba(),
    }


def test_admin_crea_operador_pendiente_sin_password_ni_sesion(
    db: Session,
    client: TestClient,
) -> None:
    _admin, token = crear_admin_autenticado(db)
    correo = correo_de_prueba()

    settings = Settings(
        database_host="localhost",
        database_port=5432,
        database_name="unused",
        database_user="unused",
        database_password=SecretStr("test-db-password"),
        activation_token_ttl_hours=24,
        activation_challenge_ttl_minutes=15,
        smtp_from_email="no-reply@example.com",
    )
    with (
        patch("app.api.rutas.operadores.get_settings", return_value=settings),
        patch("app.api.rutas.operadores.crear_transporte_correo") as fabrica,
    ):
        respuesta = solicitar_con_cookies(
            client,
            "POST",
            RUTA_CREAR_OPERADOR,
            json=datos_operador(correo),
            cookies={NOMBRE_COOKIE: token},
        )

    assert respuesta.status_code == 201
    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.json() == {"estado": "operador_creado"}
    assert correo not in respuesta.text
    assert "contrasena" not in respuesta.text.lower()
    assert "$argon2id$" not in respuesta.text
    fabrica.return_value.enviar.assert_called_once()

    db.rollback()
    operador = db.scalar(select(Usuario).where(Usuario.correo == correo))
    assert operador is not None
    assert operador.rol == RolUsuario.OPERADOR.value
    assert operador.esta_activo is True
    assert operador.correo_verificado is False
    assert operador.debe_cambiar_contrasena is False
    assert operador.contrasena_hash is None
    assert (
        db.scalar(
            select(func.count())
            .select_from(ActivacionCuenta)
            .where(ActivacionCuenta.usuario_id == operador.id)
        )
        == 1
    )
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == operador.id)
    )
    assert activacion is not None
    assert activacion.codigo_hash is None
    assert (
        db.scalar(
            select(func.count())
            .select_from(Sesion)
            .where(Sesion.usuario_id == operador.id)
        )
        == 0
    )


def test_sesion_admin_autoriza_antes_de_comprobar_correo_existente(
    db: Session,
    client: TestClient,
) -> None:
    _admin, token = crear_admin_autenticado(db)
    correo_existente = correo_de_prueba()
    crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo_existente,
        contrasena=CONTRASENA_ADMIN,
        confirmacion_contrasena=CONTRASENA_ADMIN,
    )

    with patch("app.api.rutas.operadores.crear_operador") as crear:
        respuesta = client.post(
            RUTA_CREAR_OPERADOR,
            json=datos_operador(correo_existente),
        )

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "No autenticado"}
    assert respuesta.headers["cache-control"] == "no-store"
    crear.assert_not_called()

    respuesta_autenticada = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=datos_operador(correo_existente),
        cookies={NOMBRE_COOKIE: token},
    )
    assert respuesta_autenticada.status_code == 409
    assert respuesta_autenticada.json() == {"detail": "El correo ya esta registrado."}
    assert respuesta_autenticada.headers["cache-control"] == "no-store"
    assert correo_existente not in respuesta_autenticada.text


@pytest.mark.parametrize(
    "estado",
    [
        "sin_cookie",
        "token_invalido",
        "sesion_expirada",
        "sesion_revocada",
        "cuenta_inactiva",
        "correo_no_verificado",
        "cambio_obligatorio",
        "rol_operador",
    ],
)
def test_solo_sesion_admin_vigente_puede_crear_operador(
    db: Session,
    client: TestClient,
    estado: str,
) -> None:
    cookies: dict[str, str] | None
    if estado == "sin_cookie":
        cookies = None
    elif estado == "token_invalido":
        cookies = {NOMBRE_COOKIE: "token-desconocido-sp025"}
    else:
        usuario, token = crear_admin_autenticado(db)
        sesion = db.scalar(select(Sesion).where(Sesion.usuario_id == usuario.id))
        assert sesion is not None
        if estado == "sesion_expirada":
            sesion.expira_en = datetime.now(UTC) - timedelta(seconds=1)
        elif estado == "sesion_revocada":
            sesion.revocado_en = datetime.now(UTC)
        elif estado == "cuenta_inactiva":
            usuario.esta_activo = False
        elif estado == "correo_no_verificado":
            usuario.correo_verificado = False
        elif estado == "cambio_obligatorio":
            usuario.debe_cambiar_contrasena = True
        elif estado == "rol_operador":
            usuario.rol = RolUsuario.OPERADOR.value
        db.commit()
        db.rollback()
        cookies = {NOMBRE_COOKIE: token}

    correo = correo_de_prueba()
    respuesta = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=datos_operador(correo),
        cookies=cookies,
    )

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "No autenticado"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert db.scalar(select(Usuario.id).where(Usuario.correo == correo)) is None


@pytest.mark.parametrize(
    "cambio",
    [
        {"nombre": " "},
        {"apellido_paterno": "\t"},
        {"apellido_materno": "\n"},
        {"correo": "correo-invalido"},
        {"nombre": "N" * 101},
        {"correo": "a" * 321},
        {"rol": "ADMIN"},
        {"contrasena": "Secreto no aceptado"},
        {"password": "Secreto no aceptado"},
        {"password_hash": "hash no aceptado"},
        {"esta_activo": "false"},
        {"correo_verificado": "false"},
        {"debe_cambiar_contrasena": "true"},
        {"modo": "temporal"},
        {"token": "token-no-aceptado"},
        {"sesion": "sesion-no-aceptada"},
    ],
    ids=[
        "nombre-vacio",
        "apellido-paterno-vacio",
        "apellido-materno-vacio",
        "correo-invalido",
        "nombre-largo",
        "correo-largo",
        "rol-prohibido",
        "contrasena-prohibida",
        "password-prohibido",
        "hash-prohibido",
        "estado-prohibido",
        "verificacion-prohibida",
        "cambio-contrasena-prohibido",
        "modo-prohibido",
        "token-prohibido",
        "sesion-prohibida",
    ],
)
def test_solicitud_invalida_es_sanitizada_y_no_persiste(
    db: Session,
    client: TestClient,
    cambio: dict[str, str],
) -> None:
    _admin, token = crear_admin_autenticado(db)
    payload: dict[str, object] = datos_operador()
    payload.update(cambio)

    respuesta = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=payload,
        cookies={NOMBRE_COOKIE: token},
    )

    assert respuesta.status_code == 422
    assert respuesta.json() == {"detail": "Solicitud invalida"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert all(
        not str(valor).strip() or str(valor) not in respuesta.text
        for valor in cambio.values()
    )
    assert db.scalar(select(func.count()).select_from(Usuario)) == 1


@pytest.mark.parametrize(
    "campo_omitido",
    ["nombre", "apellido_paterno", "apellido_materno", "correo"],
)
def test_cada_campo_requerido_debe_venir_en_la_solicitud(
    db: Session,
    client: TestClient,
    campo_omitido: str,
) -> None:
    _admin, token = crear_admin_autenticado(db)
    payload = datos_operador()
    payload.pop(campo_omitido)

    respuesta = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=payload,
        cookies={NOMBRE_COOKIE: token},
    )

    assert respuesta.status_code == 422
    assert respuesta.json() == {"detail": "Solicitud invalida"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert db.scalar(select(func.count()).select_from(Usuario)) == 1


def test_solicitud_rechaza_tipos_de_campo_no_textuales(
    db: Session,
    client: TestClient,
) -> None:
    _admin, token = crear_admin_autenticado(db)
    payload: dict[str, object] = datos_operador()
    payload["nombre"] = 123

    respuesta = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=payload,
        cookies={NOMBRE_COOKIE: token},
    )

    assert respuesta.status_code == 422
    assert respuesta.json() == {"detail": "Solicitud invalida"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert "123" not in respuesta.text
    assert db.scalar(select(func.count()).select_from(Usuario)) == 1


def test_fallo_de_resolucion_de_sesion_es_401_generico_y_no_cacheable(
    client: TestClient,
) -> None:
    with patch(
        "app.api.rutas.operadores.obtener_usuario_admin_por_token",
        side_effect=SQLAlchemyError("detalle interno no publico"),
    ):
        respuesta = solicitar_con_cookies(
            client,
            "POST",
            RUTA_CREAR_OPERADOR,
            json=datos_operador(),
            cookies={NOMBRE_COOKIE: "token-de-prueba-sp025"},
        )

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "No autenticado"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert "detalle interno no publico" not in respuesta.text


def test_error_de_otra_restriccion_no_se_convierte_en_correo_duplicado(
    db: Session,
    client: TestClient,
) -> None:
    _admin, token = crear_admin_autenticado(db)
    error = SQLAlchemyError("fallo de persistencia controlado")
    with patch("app.api.rutas.operadores.crear_operador", side_effect=error):
        respuesta = solicitar_con_cookies(
            client,
            "POST",
            RUTA_CREAR_OPERADOR,
            json=datos_operador(),
            cookies={NOMBRE_COOKIE: token},
        )

    assert respuesta.status_code == 500
    assert respuesta.json() == {"detail": "Error interno"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert "fallo de persistencia controlado" not in respuesta.text


def test_operador_existente_tampoco_puede_usar_su_sesion_para_crear(
    db: Session,
    client: TestClient,
) -> None:
    correo_operador = correo_de_prueba()
    operador = crear_operador_existente(db, correo_operador)
    token = crear_sesion(db, operador)

    respuesta = solicitar_con_cookies(
        client,
        "POST",
        RUTA_CREAR_OPERADOR,
        json=datos_operador(correo_de_prueba()),
        cookies={NOMBRE_COOKIE: token},
    )

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "No autenticado"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert db.scalar(select(func.count()).select_from(Usuario)) == 1
