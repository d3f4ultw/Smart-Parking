package mx.smartparking.api.recuperacion;

/** Reúne el resultado de pedir un enlace de recuperación y la versión actual de la cuenta del operador. */
public record ResultadoSolicitudRecuperacionOperador(
        RespuestaSolicitudRecuperacionOperador respuesta,
        long revisionAcceso) {
}
