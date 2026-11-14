package mx.smartparking.api.historial.persistencia;

import java.time.Instant;

/** Reúne una decisión guardada para preparar los datos que se mostrarán en el historial. */
public record FilaHistorialAcceso(
        long id,
        Instant ocurridoEn,
        String lector,
        String resultado,
        String motivo,
        String tipoPersona,
        String nombrePersona) {
}
