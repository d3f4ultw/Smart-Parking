package mx.smartparking.api.activacion;

/** Reúne el aviso de error que puede mostrarse sin revelar datos de la cuenta. */
public record RespuestaErrorActivacionOperador(String codigo, String mensaje) {
}
