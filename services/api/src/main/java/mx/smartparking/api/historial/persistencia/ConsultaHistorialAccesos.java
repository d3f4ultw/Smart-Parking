package mx.smartparking.api.historial.persistencia;

import java.util.List;

/** reúne la zona horaria, los registros de una página y si hay más resultados. */
public record ConsultaHistorialAccesos(
        String zonaHoraria,
        List<FilaHistorialAcceso> items,
        long totalRegistros,
        boolean haySiguiente) {
}
