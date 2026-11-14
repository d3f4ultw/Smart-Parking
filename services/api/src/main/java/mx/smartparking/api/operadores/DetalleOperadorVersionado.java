package mx.smartparking.api.operadores;

/** Reúne el detalle del operador y su versión para saber si cambió antes de modificarlo. */
public record DetalleOperadorVersionado(DetalleOperador detalle, long revisionAcceso) {
}
