package mx.smartparking.api.empleados;

import java.util.List;

/** Reúne una página de empleados y la referencia que permite reconocer cambios posteriores. */
public record PaginaEmpleados(
        List<Empleado> items,
        int pagina,
        int tamanoPagina,
        long totalRegistros,
        long totalPaginas,
        String cursorEventos) {
}
