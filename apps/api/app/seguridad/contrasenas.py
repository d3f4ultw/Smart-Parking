"""Validacion de contrasenas, hash Argon2id y generacion de contrasenas temporales."""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

LONGITUD_MINIMA_CONTRASENA = 10
LONGITUD_MAXIMA_CONTRASENA = 128
LONGITUD_CONTRASENA_TEMPORAL = 14
LONGITUD_CONTRASENA_OPERADOR = 16
CARACTERES_CONTRASENA_TEMPORAL = (
    "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
)
CARACTERES_MAYUSCULAS_CONTRASENA = "ABCDEFGHJKLMNPQRSTUVWXYZ"
HASHER = PasswordHasher()
HASH_DUMMY_CODIGO = (
    "$argon2id$v=19$m=65536,t=3,p=4$azUU8CMaKh+32Zl5/OCSrg$"
    "/VM6nTLeAJi30vfk72t0qLV1zLFTki7L7vg9S+g2Owk"
)
HASH_DUMMY_CONTRASENA = (
    "$argon2id$v=19$m=65536,t=3,p=4$aQG5GA/qUhOYgbRHoQ1ASA$"
    "R1CrltyUqUR6GYUMakYVpY0AZBgWhYkyOV35bh6hPSg"
)


class ContrasenaInvalidaError(ValueError):
    """Se lanza cuando una contrasena incumple la politica de la aplicacion."""


class ContrasenasNoCoincidenError(ValueError):
    """Se lanza cuando la confirmacion de la contrasena no coincide."""


def validar_contrasena(contrasena: str) -> None:
    """Valida una contrasena manual sin cambiar sus espacios intencionales."""

    if not isinstance(contrasena, str):
        raise ContrasenaInvalidaError("La contraseña no es válida.")
    if len(contrasena) < LONGITUD_MINIMA_CONTRASENA:
        raise ContrasenaInvalidaError(
            f"La contraseña debe tener al menos {LONGITUD_MINIMA_CONTRASENA} "
            "caracteres."
        )
    if len(contrasena) > LONGITUD_MAXIMA_CONTRASENA:
        raise ContrasenaInvalidaError(
            f"La contraseña no puede superar {LONGITUD_MAXIMA_CONTRASENA} caracteres."
        )
    if not contrasena.isprintable():
        raise ContrasenaInvalidaError("La contraseña contiene caracteres no válidos.")
    if not any(caracter.isupper() for caracter in contrasena):
        raise ContrasenaInvalidaError(
            "La contraseña debe incluir al menos una letra mayúscula."
        )


def validar_confirmacion_contrasena(
    contrasena: str,
    confirmacion_contrasena: str,
) -> None:
    """Valida la politica y la coincidencia exacta, incluidos los espacios."""

    validar_contrasena(contrasena)
    if contrasena != confirmacion_contrasena:
        raise ContrasenasNoCoincidenError("Las contraseñas no coinciden.")


def crear_hash_contrasena(contrasena: str) -> str:
    """Crea el hash de una contrasena con la configuracion estandar de Argon2id."""

    return HASHER.hash(contrasena)


def verificar_contrasena(contrasena: str, contrasena_hash: str) -> bool:
    """Indica si una contrasena coincide con un hash Argon2id."""

    try:
        return HASHER.verify(contrasena_hash, contrasena)
    except InvalidHashError, VerificationError, VerifyMismatchError:
        return False


def generar_contrasena_temporal() -> str:
    """Genera una contrasena temporal efimera de longitud fija y segura."""

    return "".join(
        secrets.choice(CARACTERES_CONTRASENA_TEMPORAL)
        for _ in range(LONGITUD_CONTRASENA_TEMPORAL)
    )


def generar_contrasena_operador() -> str:
    """Genera una credencial permanente de OPERADOR compatible con la politica."""

    posicion_mayuscula = secrets.randbelow(LONGITUD_CONTRASENA_OPERADOR)
    contrasena = "".join(
        secrets.choice(
            CARACTERES_MAYUSCULAS_CONTRASENA
            if posicion == posicion_mayuscula
            else CARACTERES_CONTRASENA_TEMPORAL
        )
        for posicion in range(LONGITUD_CONTRASENA_OPERADOR)
    )
    validar_contrasena(contrasena)
    return contrasena
