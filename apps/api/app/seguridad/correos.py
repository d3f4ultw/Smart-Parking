"""Normalizacion y huellas de correo usadas por la autenticacion."""

import hashlib

from email_validator import EmailNotValidError, validate_email


class CorreoInvalidoError(ValueError):
    """Se lanza cuando un correo no tiene una sintaxis valida."""


def normalizar_correo(
    correo: str,
    *,
    permitir_entorno_pruebas: bool = False,
) -> str:
    """Valida y devuelve la identidad de correo canonica sin distinguir mayusculas."""

    if not isinstance(correo, str) or not correo.strip():
        raise CorreoInvalidoError("El correo es obligatorio.")

    try:
        resultado = validate_email(
            correo.strip(),
            check_deliverability=False,
            test_environment=permitir_entorno_pruebas,
        )
    except EmailNotValidError as error:
        raise CorreoInvalidoError("El correo no es valido.") from error

    return resultado.normalized.casefold()


def huella_correo(correo_normalizado: str) -> str:
    """Devuelve una huella SHA-256 sin conservar el correo en el limiter."""

    return hashlib.sha256(correo_normalizado.encode("utf-8")).hexdigest()


__all__ = ["CorreoInvalidoError", "huella_correo", "normalizar_correo"]
