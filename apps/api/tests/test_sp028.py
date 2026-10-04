"""Pruebas SP-028 para la administracion segura de cuentas OPERADOR."""

from __future__ import annotations

import logging
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from threading import Event, Thread
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.database import get_db
from app.correo.errores import ErrorCorreo, ErrorEnvioCorreo
from app.correo.mensajes import (
    ASUNTO_REGENERACION_CREDENCIALES_OPERADOR,
    DatosActivacionCorreo,
    construir_mensaje_regeneracion_credenciales_operador,
)
from app.models import RolUsuario, Sesion, Usuario
from app.seguridad.contrasenas import (
    crear_hash_contrasena,
    validar_contrasena,
    verificar_contrasena,
)
from app.seguridad.sesiones import hash_token_sesion
from app.servicios import autenticacion as servicio_autenticacion
from app.servicios.operadores import desactivar_operador, regenerar_contrasena_operador
from app.servicios.usuarios import crear_admin
from main import app

RUTA_OPERADORES = "/api/admin/operadores"
NOMBRE_COOKIE = "smart_parking_session"
CONTRASENA_ADMIN = "Contrasena segura SP028 123"
CONTRASENA_OPERADOR = "Operador anterior SP028 123"


class TransporteFalso:
    """Acepta mensajes en memoria o simula un error de entrega tipado."""

    def __init__(self, error: ErrorCorreo | None = None) -> None:
        self.mensajes: list[EmailMessage] = []
        self.error = error

    def enviar(self, datos: DatosActivacionCorreo | EmailMessage) -> None:
        if self.error is not None:
            raise self.error
        if not isinstance(datos, EmailMessage):
            raise ErrorEnvioCorreo
        self.mensajes.append(datos)


def correo_de_prueba() -> str:
    return f"sp028-test-{uuid4().hex}@example.com"


def settings_de_prueba(**overrides: Any) -> Settings:
    valores: dict[str, Any] = {
        "database_host": "localhost",
        "database_port": 5432,
        "database_name": "unused",
        "database_user": "unused",
        "database_password": "test-db-password",
        "activation_token_ttl_hours": 24,
        "activation_challenge_ttl_minutes": 15,
        "app_environment": "development",
        "correo_transporte": "smtp",
        "smtp_host": "smtp.test.invalid",
        "smtp_port": "465",
        "smtp_username": "smtp-user",
        "smtp_password": SecretStr("smtp-secret-no-output"),
        "smtp_from_email": "no-reply@example.com",
        "smtp_from_name": "Smart Parking",
        "smtp_security": "ssl",
        "smtp_timeout_seconds": "10",
    }
    valores.update(overrides)
    return Settings(**valores)


def crear_admin_autenticado(db: Session) -> str:
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

    token = f"token-sp028-admin-{uuid4().hex}"
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


def crear_operador_prueba(
    db: Session,
    *,
    correo: str | None = None,
    esta_activo: bool = True,
) -> Usuario:
    usuario = Usuario(
        nombre="Grace",
        apellido_paterno="Hopper",
        apellido_materno="Murray",
        correo=correo or correo_de_prueba(),
        contrasena_hash=crear_hash_contrasena(CONTRASENA_OPERADOR),
        rol=RolUsuario.OPERADOR.value,
        correo_verificado=True,
        esta_activo=esta_activo,
        debe_cambiar_contrasena=False,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    db.rollback()
    return usuario


def agregar_sesion(
    db: Session,
    usuario: Usuario,
    *,
    expira_en: datetime | None = None,
) -> str:
    token = f"token-sp028-operador-{uuid4().hex}"
    ahora = datetime.now(UTC)
    db.add(
        Sesion(
            usuario_id=usuario.id,
            token_hash=hash_token_sesion(token),
            expira_en=expira_en or ahora + timedelta(minutes=30),
            revocado_en=None,
            creado_en=ahora,
        )
    )
    db.commit()
    db.rollback()
    return token


def contrasena_del_mensaje(mensaje: EmailMessage) -> str:
    cuerpo = mensaje.get_body(preferencelist=("plain",))
    assert cuerpo is not None
    linea = next(
        linea
        for linea in cuerpo.get_content().splitlines()
        if linea.startswith("Contrasena: ")
    )
    return linea.removeprefix("Contrasena: ")


def solicitar_con_cookie(
    client: TestClient,
    metodo: str,
    ruta: str,
    *,
    token: str | None = None,
) -> Any:
    """Fija o quita la cookie de sesión en el cliente de pruebas."""

    client.cookies.clear()
    if token is not None:
        client.cookies.set(
            NOMBRE_COOKIE,
            token,
            domain="testserver.local",
            path="/",
        )
    return client.request(metodo, ruta)


@pytest.fixture
def client(database_url: URL) -> Generator[TestClient]:
    """Expone la API conectada a la base temporal de esta suite."""

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


@pytest.fixture
def transporte_falso(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TransporteFalso, Settings]:
    transporte = TransporteFalso()
    settings = settings_de_prueba()
    monkeypatch.setattr("app.api.rutas.operadores.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.api.rutas.operadores.crear_transporte_correo",
        lambda _settings: transporte,
    )
    return transporte, settings


def test_admin_lista_y_consulta_solo_operadores_con_campos_permitidos(
    db: Session,
    client: TestClient,
) -> None:
    token = crear_admin_autenticado(db)
    operador_a = crear_operador_prueba(db, correo=correo_de_prueba())
    operador_b = crear_operador_prueba(db, correo=correo_de_prueba())
    otro_admin = crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo_de_prueba(),
        contrasena=CONTRASENA_ADMIN,
        confirmacion_contrasena=CONTRASENA_ADMIN,
    ).usuario

    respuesta = solicitar_con_cookie(client, "GET", RUTA_OPERADORES, token=token)

    assert respuesta.status_code == 200
    assert respuesta.headers["cache-control"] == "no-store"
    cuerpo = respuesta.json()
    filas = cuerpo["operadores"]
    assert [fila["id"] for fila in filas] == sorted([operador_a.id, operador_b.id])
    assert {
        clave: cuerpo[clave]
        for clave in ("pagina", "tamano_pagina", "total", "total_paginas")
    } == {"pagina": 1, "tamano_pagina": 10, "total": 2, "total_paginas": 1}
    assert all(
        set(fila)
        == {
            "id",
            "nombre",
            "apellido_paterno",
            "apellido_materno",
            "correo",
            "esta_activo",
            "estado_cuenta",
        }
        for fila in filas
    )
    assert all(fila["estado_cuenta"] == "acceso_habilitado" for fila in filas)
    assert all(fila["id"] != otro_admin.id for fila in filas)
    assert "contrasena_hash" not in respuesta.text
    assert "correo_verificado" not in respuesta.text
    assert "debe_cambiar_contrasena" not in respuesta.text

    detalle = solicitar_con_cookie(
        client,
        "GET",
        f"{RUTA_OPERADORES}/{operador_a.id}",
        token=token,
    )
    assert detalle.status_code == 200
    assert detalle.headers["cache-control"] == "no-store"
    assert set(detalle.json()) == set(filas[0])
    assert detalle.json()["correo"] == operador_a.correo
    assert detalle.json()["estado_cuenta"] == "acceso_habilitado"

    detalle_admin = solicitar_con_cookie(
        client,
        "GET",
        f"{RUTA_OPERADORES}/{otro_admin.id}",
        token=token,
    )
    detalle_ausente = solicitar_con_cookie(
        client,
        "GET",
        f"{RUTA_OPERADORES}/999999",
        token=token,
    )
    assert detalle_admin.status_code == detalle_ausente.status_code == 404


def test_admin_lista_operadores_pagina_diez_elementos_y_limpia_pagina_fuera_de_rango(
    db: Session,
    client: TestClient,
) -> None:
    token = crear_admin_autenticado(db)
    hash_operador = crear_hash_contrasena(CONTRASENA_OPERADOR)
    operadores = [
        Usuario(
            nombre=f"Operador {indice:02d}",
            apellido_paterno="Prueba",
            apellido_materno="Paginacion",
            correo=correo_de_prueba(),
            contrasena_hash=hash_operador,
            rol=RolUsuario.OPERADOR.value,
            correo_verificado=indice != 2,
            debe_cambiar_contrasena=indice == 2 or indice == 3,
            esta_activo=indice % 2 == 0,
        )
        for indice in range(21)
    ]
    db.add_all(operadores)
    db.commit()
    ids_ordenados = sorted(operador.id for operador in operadores)
    db.rollback()

    primera = solicitar_con_cookie(
        client,
        "GET",
        RUTA_OPERADORES,
        token=token,
    )
    segunda = solicitar_con_cookie(
        client,
        "GET",
        f"{RUTA_OPERADORES}?pagina=2",
        token=token,
    )
    ultima = solicitar_con_cookie(
        client,
        "GET",
        f"{RUTA_OPERADORES}?pagina=3",
        token=token,
    )
    fuera_de_rango = solicitar_con_cookie(
        client,
        "GET",
        f"{RUTA_OPERADORES}?pagina=99",
        token=token,
    )

    assert primera.status_code == segunda.status_code == ultima.status_code == 200
    assert primera.headers["cache-control"] == "no-store"
    assert [fila["id"] for fila in primera.json()["operadores"]] == ids_ordenados[:10]
    assert [fila["id"] for fila in segunda.json()["operadores"]] == ids_ordenados[10:20]
    assert [fila["id"] for fila in ultima.json()["operadores"]] == ids_ordenados[20:]
    assert primera.json()["total"] == segunda.json()["total"] == 21
    assert primera.json()["total_paginas"] == segunda.json()["total_paginas"] == 3
    assert segunda.json()["pagina"] == 2
    assert ultima.json()["pagina"] == 3
    assert fuera_de_rango.json()["pagina"] == 3
    assert fuera_de_rango.json()["operadores"] == ultima.json()["operadores"]
    assert len(primera.json()["operadores"]) == len(segunda.json()["operadores"]) == 10
    assert len(ultima.json()["operadores"]) == 1
    assert set(ids_ordenados[:10]).isdisjoint(ids_ordenados[10:20])
    assert set(ids_ordenados[10:20]).isdisjoint(ids_ordenados[20:])

    pagina_estado_pendiente = solicitar_con_cookie(
        client,
        "GET",
        f"{RUTA_OPERADORES}?pagina=1",
        token=token,
    ).json()["operadores"]
    estado_por_id = {
        fila["id"]: fila["estado_cuenta"] for fila in pagina_estado_pendiente
    }
    assert estado_por_id[ids_ordenados[2]] == "pendiente_activacion"
    assert estado_por_id[ids_ordenados[3]] == "inactivo"
    assert "correo_verificado" not in primera.text
    assert "debe_cambiar_contrasena" not in primera.text
    assert "contrasena_hash" not in primera.text


def test_admin_lista_operadores_sin_resultados_y_rechaza_pagina_no_positiva(
    db: Session,
    client: TestClient,
) -> None:
    token = crear_admin_autenticado(db)

    vacia = solicitar_con_cookie(client, "GET", RUTA_OPERADORES, token=token)
    invalida = solicitar_con_cookie(
        client,
        "GET",
        f"{RUTA_OPERADORES}?pagina=0",
        token=token,
    )

    assert vacia.status_code == 200
    assert vacia.json() == {
        "operadores": [],
        "pagina": 1,
        "tamano_pagina": 10,
        "total": 0,
        "total_paginas": 0,
    }
    assert vacia.headers["cache-control"] == "no-store"
    assert invalida.status_code == 422
    assert invalida.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [
        ("GET", RUTA_OPERADORES),
        ("GET", f"{RUTA_OPERADORES}/1"),
        ("POST", f"{RUTA_OPERADORES}/1/desactivar"),
        ("POST", f"{RUTA_OPERADORES}/1/reactivar"),
        ("POST", f"{RUTA_OPERADORES}/1/regenerar-contrasena"),
        ("POST", f"{RUTA_OPERADORES}/1/reenviar-invitacion"),
    ],
)
def test_todas_las_rutas_de_gestion_exigen_sesion_admin(
    db: Session,
    client: TestClient,
    metodo: str,
    ruta: str,
) -> None:
    operador = crear_operador_prueba(db)
    token_operador = agregar_sesion(db, operador)
    db.rollback()
    token_admin_revocado = crear_admin_autenticado(db)
    sesion_admin = db.scalar(
        select(Sesion).where(
            Sesion.token_hash == hash_token_sesion(token_admin_revocado)
        )
    )
    if sesion_admin is None:
        pytest.fail("No se encontro la sesion sintetica ADMIN para revocar.")
    sesion_admin.revocado_en = datetime.now(UTC)
    db.commit()
    db.rollback()

    respuesta_anonima = solicitar_con_cookie(client, metodo, ruta)
    respuesta_operador = solicitar_con_cookie(
        client,
        metodo,
        ruta,
        token=token_operador,
    )
    respuesta_cookie_invalida = solicitar_con_cookie(
        client,
        metodo,
        ruta,
        token="token-invalido-sp028",
    )
    respuesta_sesion_revocada = solicitar_con_cookie(
        client,
        metodo,
        ruta,
        token=token_admin_revocado,
    )

    assert respuesta_anonima.status_code == 401
    assert respuesta_operador.status_code == 401
    assert respuesta_cookie_invalida.status_code == 401
    assert respuesta_sesion_revocada.status_code == 401
    assert respuesta_operador.headers["cache-control"] == "no-store"


def test_mutaciones_devuelven_404_para_id_ausente_o_rol_distinto(
    db: Session,
    client: TestClient,
    transporte_falso: tuple[TransporteFalso, Settings],
) -> None:
    transporte, _settings = transporte_falso
    token_admin = crear_admin_autenticado(db)
    admin_ajeno = crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo_de_prueba(),
        contrasena=CONTRASENA_ADMIN,
        confirmacion_contrasena=CONTRASENA_ADMIN,
    ).usuario

    for operador_id in (admin_ajeno.id, 999999):
        for accion in (
            "desactivar",
            "reactivar",
            "regenerar-contrasena",
            "reenviar-invitacion",
        ):
            respuesta = solicitar_con_cookie(
                client,
                "POST",
                f"{RUTA_OPERADORES}/{operador_id}/{accion}",
                token=token_admin,
            )
            assert respuesta.status_code == 404
            assert respuesta.headers["cache-control"] == "no-store"
            assert respuesta.json() == {"detail": "Operador no encontrado"}

    assert transporte.mensajes == []


def test_desactivar_revoca_todas_las_sesiones_y_reactivar_no_las_recupera(
    db: Session,
    client: TestClient,
) -> None:
    token_admin = crear_admin_autenticado(db)
    operador = crear_operador_prueba(db)
    hash_anterior = operador.contrasena_hash
    token_vigente = agregar_sesion(db, operador)
    agregar_sesion(
        db,
        operador,
        expira_en=datetime.now(UTC) - timedelta(days=1),
    )

    desactivar = solicitar_con_cookie(
        client,
        "POST",
        f"{RUTA_OPERADORES}/{operador.id}/desactivar",
        token=token_admin,
    )

    assert desactivar.status_code == 200
    assert desactivar.headers["cache-control"] == "no-store"
    assert desactivar.json() == {"estado": "operador_desactivado"}
    db.rollback()
    db.expire_all()
    usuario = db.get(Usuario, operador.id)
    assert usuario is not None and usuario.esta_activo is False
    sesiones = db.scalars(
        select(Sesion).where(Sesion.usuario_id == operador.id).order_by(Sesion.id)
    ).all()
    assert len(sesiones) == 2
    assert all(sesion.revocado_en is not None for sesion in sesiones)
    assert (
        db.scalar(
            select(func.count()).select_from(Usuario).where(Usuario.id == operador.id)
        )
        == 1
    )
    assert (
        solicitar_con_cookie(
            client,
            "GET",
            "/api/autenticacion/me",
            token=token_vigente,
        ).status_code
        == 401
    )
    login_inactivo = client.post(
        "/api/autenticacion/login",
        json={"correo": operador.correo, "contrasena": CONTRASENA_OPERADOR},
    )
    assert login_inactivo.status_code == 401
    assert login_inactivo.json() == {"detail": "Credenciales invalidas"}

    repetida = solicitar_con_cookie(
        client,
        "POST",
        f"{RUTA_OPERADORES}/{operador.id}/desactivar",
        token=token_admin,
    )
    assert repetida.status_code == 409

    reactivar = solicitar_con_cookie(
        client,
        "POST",
        f"{RUTA_OPERADORES}/{operador.id}/reactivar",
        token=token_admin,
    )
    assert reactivar.status_code == 200
    assert reactivar.headers["cache-control"] == "no-store"
    assert reactivar.json() == {"estado": "operador_reactivado"}
    db.rollback()
    usuario = db.get(Usuario, operador.id)
    assert usuario is not None
    assert usuario.esta_activo is True
    assert usuario.contrasena_hash == hash_anterior
    assert usuario.correo_verificado is True
    assert usuario.debe_cambiar_contrasena is False
    assert all(
        sesion.revocado_en is not None
        for sesion in db.scalars(
            select(Sesion).where(Sesion.usuario_id == operador.id)
        ).all()
    )
    assert (
        solicitar_con_cookie(
            client,
            "GET",
            "/api/autenticacion/me",
            token=token_vigente,
        ).status_code
        == 401
    )

    login_nuevo = client.post(
        "/api/autenticacion/login",
        json={"correo": operador.correo, "contrasena": CONTRASENA_OPERADOR},
    )
    assert login_nuevo.status_code == 200
    assert login_nuevo.json()["rol"] == RolUsuario.OPERADOR.value
    token_nuevo = login_nuevo.cookies[NOMBRE_COOKIE]
    assert (
        solicitar_con_cookie(
            client,
            "GET",
            "/api/autenticacion/me",
            token=token_nuevo,
        ).status_code
        == 200
    )
    repetida = solicitar_con_cookie(
        client,
        "POST",
        f"{RUTA_OPERADORES}/{operador.id}/reactivar",
        token=token_admin,
    )
    assert repetida.status_code == 409


def test_regenerar_contrasena_entrega_credencial_nueva_y_revoca_sesiones(
    db: Session,
    client: TestClient,
    transporte_falso: tuple[TransporteFalso, Settings],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    transporte, _settings = transporte_falso
    token_admin = crear_admin_autenticado(db)
    operador = crear_operador_prueba(db)
    hash_anterior = operador.contrasena_hash
    if hash_anterior is None:
        pytest.fail("El OPERADOR sintetico no tenia una credencial inicial.")
    token_vigente = agregar_sesion(db, operador)
    agregar_sesion(
        db,
        operador,
        expira_en=datetime.now(UTC) - timedelta(days=1),
    )

    respuesta = solicitar_con_cookie(
        client,
        "POST",
        f"{RUTA_OPERADORES}/{operador.id}/regenerar-contrasena",
        token=token_admin,
    )

    assert respuesta.status_code == 200
    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.json() == {"estado": "contrasena_regenerada"}
    assert len(transporte.mensajes) == 1
    mensaje = transporte.mensajes[0]
    assert mensaje["To"] == operador.correo
    assert mensaje["Subject"] == ASUNTO_REGENERACION_CREDENCIALES_OPERADOR
    cuerpo = mensaje.get_body(preferencelist=("plain",))
    assert cuerpo is not None
    assert "Se regeneró la contraseña" in cuerpo.get_content()
    contrasena_nueva = contrasena_del_mensaje(mensaje)
    validar_contrasena(contrasena_nueva)
    if contrasena_nueva == CONTRASENA_OPERADOR:
        pytest.fail("La credencial regenerada coincide con la credencial anterior.")
    if contrasena_nueva in respuesta.text or hash_anterior in respuesta.text:
        pytest.fail("La respuesta API expuso material de credenciales.")
    if contrasena_nueva in caplog.text or hash_anterior in caplog.text:
        pytest.fail("Los logs expusieron material de credenciales.")
    assert "token" not in respuesta.text.casefold()

    db.rollback()
    db.expire_all()
    usuario = db.get(Usuario, operador.id)
    assert usuario is not None
    assert usuario.contrasena_hash is not None
    if usuario.contrasena_hash == hash_anterior:
        pytest.fail("La regeneracion no reemplazo el hash anterior.")
    if not verificar_contrasena(contrasena_nueva, usuario.contrasena_hash):
        pytest.fail("La credencial entregada no corresponde con el hash almacenado.")
    assert not verificar_contrasena(CONTRASENA_OPERADOR, usuario.contrasena_hash)
    assert usuario.esta_activo is True
    assert usuario.correo_verificado is True
    assert usuario.debe_cambiar_contrasena is False
    sesiones = db.scalars(select(Sesion).where(Sesion.usuario_id == operador.id)).all()
    assert len(sesiones) == 2
    assert all(sesion.revocado_en is not None for sesion in sesiones)
    assert (
        solicitar_con_cookie(
            client,
            "GET",
            "/api/autenticacion/me",
            token=token_vigente,
        ).status_code
        == 401
    )

    login_anterior = client.post(
        "/api/autenticacion/login",
        json={"correo": operador.correo, "contrasena": CONTRASENA_OPERADOR},
    )
    login_nuevo = client.post(
        "/api/autenticacion/login",
        json={"correo": operador.correo, "contrasena": contrasena_nueva},
    )
    assert login_anterior.status_code == 401
    assert login_nuevo.status_code == 200
    assert login_nuevo.json()["rol"] == RolUsuario.OPERADOR.value


def test_regenerar_contrasena_conserva_el_estado_inactivo(
    db: Session,
    client: TestClient,
    transporte_falso: tuple[TransporteFalso, Settings],
) -> None:
    transporte, _settings = transporte_falso
    token_admin = crear_admin_autenticado(db)
    operador = crear_operador_prueba(db, esta_activo=False)
    hash_anterior = operador.contrasena_hash

    respuesta = solicitar_con_cookie(
        client,
        "POST",
        f"{RUTA_OPERADORES}/{operador.id}/regenerar-contrasena",
        token=token_admin,
    )

    assert respuesta.status_code == 409
    assert transporte.mensajes == []
    db.rollback()
    db.expire_all()
    usuario = db.get(Usuario, operador.id)
    assert usuario is not None
    assert usuario.esta_activo is False
    assert usuario.contrasena_hash == hash_anterior


def test_fallo_de_entrega_revierte_hash_y_revocacion_y_responde_generico(
    db: Session,
    client: TestClient,
    transporte_falso: tuple[TransporteFalso, Settings],
) -> None:
    transporte, _settings = transporte_falso
    transporte.error = ErrorEnvioCorreo()
    token_admin = crear_admin_autenticado(db)
    operador = crear_operador_prueba(db)
    hash_anterior = operador.contrasena_hash
    token_vigente = agregar_sesion(db, operador)

    respuesta = solicitar_con_cookie(
        client,
        "POST",
        f"{RUTA_OPERADORES}/{operador.id}/regenerar-contrasena",
        token=token_admin,
    )

    assert respuesta.status_code == 503
    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.json() == {
        "detail": "Servicio de correo temporalmente no disponible"
    }
    assert hash_anterior not in respuesta.text
    assert operador.correo not in respuesta.text
    assert transporte.mensajes == []
    db.rollback()
    db.expire_all()
    usuario = db.get(Usuario, operador.id)
    sesion = db.scalar(
        select(Sesion).where(Sesion.token_hash == hash_token_sesion(token_vigente))
    )
    assert usuario is not None and usuario.contrasena_hash == hash_anterior
    assert usuario.contrasena_hash is not None
    assert verificar_contrasena(CONTRASENA_OPERADOR, usuario.contrasena_hash)
    assert sesion is not None and sesion.revocado_en is None
    assert (
        solicitar_con_cookie(
            client,
            "GET",
            "/api/autenticacion/me",
            token=token_vigente,
        ).status_code
        == 200
    )


def test_error_al_construir_correo_revierte_cambio_y_responde_503(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    transporte_falso: tuple[TransporteFalso, Settings],
) -> None:
    transporte, _settings = transporte_falso
    configuracion_invalida = settings_de_prueba(smtp_from_email=None)
    monkeypatch.setattr(
        "app.api.rutas.operadores.get_settings",
        lambda: configuracion_invalida,
    )
    token_admin = crear_admin_autenticado(db)
    operador = crear_operador_prueba(db)
    hash_anterior = operador.contrasena_hash
    token_vigente = agregar_sesion(db, operador)

    respuesta = solicitar_con_cookie(
        client,
        "POST",
        f"{RUTA_OPERADORES}/{operador.id}/regenerar-contrasena",
        token=token_admin,
    )

    assert respuesta.status_code == 503
    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.json() == {
        "detail": "Servicio de correo temporalmente no disponible"
    }
    assert transporte.mensajes == []
    db.rollback()
    db.expire_all()
    usuario = db.get(Usuario, operador.id)
    sesion = db.scalar(
        select(Sesion).where(Sesion.token_hash == hash_token_sesion(token_vigente))
    )
    assert usuario is not None and usuario.contrasena_hash == hash_anterior
    assert usuario.contrasena_hash is not None
    assert verificar_contrasena(CONTRASENA_OPERADOR, usuario.contrasena_hash)
    assert sesion is not None and sesion.revocado_en is None


def test_fallo_de_commit_despues_de_aceptacion_smtp_revierte_db_sin_reintento(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transporte = TransporteFalso()
    settings = settings_de_prueba()
    operador = crear_operador_prueba(db)
    hash_anterior = operador.contrasena_hash
    token_vigente = agregar_sesion(db, operador)

    def entregar(usuario: Usuario, contrasena: str) -> None:
        transporte.enviar(
            construir_mensaje_regeneracion_credenciales_operador(
                usuario,
                contrasena,
                settings=settings,
            )
        )

    def fallar_commit(_sesion: Session) -> None:
        raise SQLAlchemyError("detalle interno con credencial")

    event.listen(db, "before_commit", fallar_commit)
    try:
        with pytest.raises(SQLAlchemyError, match="detalle interno"):
            regenerar_contrasena_operador(
                db,
                operador.id,
                entregar_credencial=entregar,
            )
    finally:
        event.remove(db, "before_commit", fallar_commit)
        db.rollback()

    assert len(transporte.mensajes) == 1
    contrasena_entregada = contrasena_del_mensaje(transporte.mensajes[0])
    db.expire_all()
    usuario = db.get(Usuario, operador.id)
    sesion = db.scalar(
        select(Sesion).where(Sesion.token_hash == hash_token_sesion(token_vigente))
    )
    assert usuario is not None and usuario.contrasena_hash == hash_anterior
    assert usuario.contrasena_hash is not None
    assert verificar_contrasena(CONTRASENA_OPERADOR, usuario.contrasena_hash)
    assert not verificar_contrasena(contrasena_entregada, usuario.contrasena_hash)
    assert sesion is not None and sesion.revocado_en is None

    # La API no filtra el detalle SQLAlchemy ni reintenta una entrega aceptada.
    db.rollback()
    token_admin = crear_admin_autenticado(db)

    def fallar_servicio(*_args: Any, **_kwargs: Any) -> None:
        raise SQLAlchemyError("detalle interno con credencial")

    monkeypatch.setattr(
        "app.api.rutas.operadores.regenerar_contrasena_operador",
        fallar_servicio,
    )
    monkeypatch.setattr(
        "app.api.rutas.operadores.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "app.api.rutas.operadores.crear_transporte_correo",
        lambda _settings: transporte,
    )
    respuesta = solicitar_con_cookie(
        client,
        "POST",
        f"{RUTA_OPERADORES}/{operador.id}/regenerar-contrasena",
        token=token_admin,
    )
    assert respuesta.status_code == 500
    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.json() == {"detail": "Error interno"}
    assert "detalle interno" not in respuesta.text
    assert contrasena_entregada not in respuesta.text
    assert len(transporte.mensajes) == 1


def test_login_concurrente_se_serializa_con_la_desactivacion(
    db: Session,
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operador = crear_operador_prueba(db)
    operador_id = operador.id
    correo = operador.correo
    hash_objetivo = operador.contrasena_hash
    db.rollback()

    engine = create_engine(database_url, pool_pre_ping=True)
    fabrica_sesiones = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    bloqueo_login_adquirido = Event()
    liberar_login = Event()
    desactivacion_iniciada = Event()
    desactivacion_terminada = Event()
    resultados: dict[str, Any] = {}
    errores: list[BaseException] = []
    verificar_original = servicio_autenticacion.verificar_contrasena

    def verificar_y_pausar(contrasena: str, hash_guardado: str) -> bool:
        coincide = verificar_original(contrasena, hash_guardado)
        if coincide and hash_guardado == hash_objetivo:
            bloqueo_login_adquirido.set()
            if not liberar_login.wait(10):
                raise TimeoutError("No se libero la prueba de concurrencia")
        return coincide

    def iniciar_sesion() -> None:
        db_hilo = fabrica_sesiones()
        try:
            resultados["sesion"] = servicio_autenticacion.crear_sesion_usuario(
                db_hilo,
                correo=correo,
                contrasena=CONTRASENA_OPERADOR,
                correo_normalizado=correo,
                duracion_minutos=30,
            )
        except BaseException as error:  # se propaga al hilo principal al terminar
            errores.append(error)
        finally:
            db_hilo.close()

    def desactivar() -> None:
        db_hilo = fabrica_sesiones()
        desactivacion_iniciada.set()
        try:
            desactivar_operador(db_hilo, operador_id)
        except BaseException as error:  # se propaga al hilo principal al terminar
            errores.append(error)
        finally:
            db_hilo.close()
            desactivacion_terminada.set()

    monkeypatch.setattr(
        "app.servicios.autenticacion.generar_token_sesion",
        lambda: "token-sp028-login-concurrente",
    )
    monkeypatch.setattr(
        "app.servicios.autenticacion.verificar_contrasena",
        verificar_y_pausar,
    )
    hilo_login = Thread(target=iniciar_sesion, daemon=True)
    hilo_desactivar = Thread(target=desactivar, daemon=True)
    try:
        hilo_login.start()
        assert bloqueo_login_adquirido.wait(10)
        hilo_desactivar.start()
        assert desactivacion_iniciada.wait(10)
        assert not desactivacion_terminada.wait(0.3)
    finally:
        liberar_login.set()
        hilo_login.join(timeout=10)
        if hilo_desactivar.ident is not None:
            hilo_desactivar.join(timeout=10)
        engine.dispose()

    assert not hilo_login.is_alive()
    assert not hilo_desactivar.is_alive()
    assert errores == []
    assert resultados["sesion"] is not None
    db.expire_all()
    usuario_final = db.get(Usuario, operador_id)
    assert usuario_final is not None and usuario_final.esta_activo is False
    sesion = db.scalar(
        select(Sesion).where(
            Sesion.token_hash == hash_token_sesion("token-sp028-login-concurrente")
        )
    )
    assert sesion is not None and sesion.revocado_en is not None
