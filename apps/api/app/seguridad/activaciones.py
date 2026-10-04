"""Generacion y almacenamiento seguro de credenciales de activacion."""

import hashlib
import secrets

from app.seguridad.contrasenas import crear_hash_contrasena

LONGITUD_TOKEN_BYTES = 32
LONGITUD_CODIGO = 6


def generar_token_activacion() -> str:
    """Genera un token de activacion criptograficamente aleatorio."""

    return secrets.token_urlsafe(LONGITUD_TOKEN_BYTES)


def generar_codigo_verificacion() -> str:
    """Genera un codigo decimal de seis digitos, incluidos ceros iniciales."""

    return f"{secrets.randbelow(1_000_000):0{LONGITUD_CODIGO}d}"


def hash_token_activacion(token: str) -> str:
    """Devuelve el SHA-256 determinista del token, nunca el token original."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_codigo_verificacion(codigo: str) -> str:
    """Devuelve un hash Argon2id para el codigo de baja entropia."""

    return crear_hash_contrasena(codigo)


__all__ = [
    "LONGITUD_CODIGO",
    "LONGITUD_TOKEN_BYTES",
    "generar_codigo_verificacion",
    "generar_token_activacion",
    "hash_codigo_verificacion",
    "hash_token_activacion",
]
