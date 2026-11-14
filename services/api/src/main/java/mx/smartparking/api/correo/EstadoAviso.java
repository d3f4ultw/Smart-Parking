package mx.smartparking.api.correo;

/** Indica si un aviso por correo se envió o qué ocurrió en el único intento de envío. */
public enum EstadoAviso {
    ENVIADO,
    FALLIDO,
    DESHABILITADO,
    DESCONOCIDO
}
