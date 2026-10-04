"""Pruebas SP-029 para la autorización reutilizable de OPERADOR."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.dependencias import exigir_operador
from app.core.config import get_settings
from app.models import RolUsuario, Sesion, Usuario
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.usuarios import crear_admin


def crear_usuario_prueba(db: Session, rol: RolUsuario) -> Usuario:
    """Crea una cuenta sintética utilizable sin activar transporte de correo."""

    contrasena = f"Temporal-{uuid4().hex}-A1"
    resultado = crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=f"sp029-{uuid4().hex}@example.com",
        contrasena=contrasena,
        confirmacion_contrasena=contrasena,
    )
    usuario = resultado.usuario
    usuario.rol = rol.value
    usuario.correo_verificado = True
    usuario.esta_activo = True
    usuario.debe_cambiar_contrasena = False
    db.commit()
    return usuario


def crear_sesion_prueba(
    db: Session,
    usuario: Usuario,
    *,
    expirada: bool = False,
    revocada: bool = False,
) -> str:
    """Persiste una sesión sintética y devuelve el token solo al test."""

    ahora = datetime.now(UTC)
    token = f"token-sp029-{uuid4().hex}"
    db.add(
        Sesion(
            usuario_id=usuario.id,
            token_hash=hash_token_sesion(token),
            expira_en=(
                ahora - timedelta(seconds=1)
                if expirada
                else ahora + timedelta(minutes=30)
            ),
            revocado_en=ahora if revocada else None,
            creado_en=ahora,
        )
    )
    db.commit()
    return token


def crear_request(token: str | None) -> Request:
    """Construye una solicitud con la cookie de sesión configurada."""

    encabezados: list[tuple[bytes, bytes]] = []
    if token is not None:
        nombre_cookie = get_settings().session_cookie_name
        encabezados.append((b"cookie", f"{nombre_cookie}={token}".encode("ascii")))
    return Request({"type": "http", "headers": encabezados})


def test_exigir_operador_devuelve_cuenta_activa_y_sin_cache(
    db: Session,
) -> None:
    usuario = crear_usuario_prueba(db, RolUsuario.OPERADOR)
    token = crear_sesion_prueba(db, usuario)
    response = Response()

    usuario_autorizado = exigir_operador(crear_request(token), response, db)

    assert usuario_autorizado.id == usuario.id
    assert usuario_autorizado.rol == RolUsuario.OPERADOR.value
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "estado",
    ["admin", "anonimo", "cookie_invalida", "expirada", "revocada", "inactiva"],
)
def test_exigir_operador_rechaza_sesiones_no_autorizadas(
    db: Session,
    estado: str,
) -> None:
    token: str | None
    if estado == "anonimo":
        token = None
    elif estado == "cookie_invalida":
        token = "token-invalido-sp029"
    else:
        rol = RolUsuario.ADMIN if estado == "admin" else RolUsuario.OPERADOR
        usuario = crear_usuario_prueba(db, rol)
        token = crear_sesion_prueba(
            db,
            usuario,
            expirada=estado == "expirada",
            revocada=estado == "revocada",
        )
        if estado == "inactiva":
            usuario.esta_activo = False
            db.commit()

    response = Response()
    with pytest.raises(HTTPException) as error:
        exigir_operador(crear_request(token), response, db)

    assert error.value.status_code == 401
    assert error.value.detail == "No autenticado"
    assert error.value.headers == {"Cache-Control": "no-store"}
    assert response.headers["cache-control"] == "no-store"
