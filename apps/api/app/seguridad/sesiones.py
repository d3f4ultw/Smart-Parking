"""Generacion segura de tokens opacos para sesiones del servidor."""

import hashlib
import secrets

LONGITUD_TOKEN_SESION_BYTES = 32


def generar_token_sesion() -> str:
    """Genera un token de sesión criptográficamente aleatorio."""

    return secrets.token_urlsafe(LONGITUD_TOKEN_SESION_BYTES)


def hash_token_sesion(token: str) -> str:
    """Deriva el SHA-256 determinista sin conservar el token original."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


__all__ = [
    "LONGITUD_TOKEN_SESION_BYTES",
    "generar_token_sesion",
    "hash_token_sesion",
]
