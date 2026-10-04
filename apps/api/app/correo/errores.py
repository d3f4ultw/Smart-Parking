"""Errores seguros compartidos por los transportes de correo."""


class ErrorCorreo(ValueError):
    """Clase base para errores esperados relacionados con correo."""


class ConfiguracionSMTPInvalidaError(ErrorCorreo):
    """Se lanza cuando falta o es invalida la configuracion SMTP."""

    def __init__(self, campo: str = "SMTP") -> None:
        super().__init__(f"La configuracion SMTP no es valida para {campo}.")


class ErrorEnvioCorreo(ErrorCorreo):
    """Se lanza cuando el unico intento de entrega no puede completarse."""

    def __init__(self) -> None:
        super().__init__("No fue posible enviar el correo de activacion.")


__all__ = [
    "ConfiguracionSMTPInvalidaError",
    "ErrorCorreo",
    "ErrorEnvioCorreo",
]
