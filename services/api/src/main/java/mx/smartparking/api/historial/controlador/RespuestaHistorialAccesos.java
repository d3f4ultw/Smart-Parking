package mx.smartparking.api.historial.controlador;

import java.util.List;

/** Reúne una página de entradas y salidas, el total encontrado y la zona horaria para mostrar el historial. */
public record RespuestaHistorialAccesos(
        List<Item> items,
        int pagina,
        int tamano,
        long totalRegistros,
        boolean haySiguiente,
        String zonaHoraria,
        String cursorEventos) {

    /** Describe la decisión guardada para una lectura de tarjeta de entrada o salida. */
    public record Item(
            long id,
            String ocurridoEn,
            String ocurridoEnLocal,
            String lector,
            String resultado,
            String motivo,
            Persona persona) {
    }

    /** Reúne el tipo y el nombre de la persona asociada a la tarjeta cuando esa relación todavía existe. */
    public record Persona(String tipo, String nombre) {
    }
}
