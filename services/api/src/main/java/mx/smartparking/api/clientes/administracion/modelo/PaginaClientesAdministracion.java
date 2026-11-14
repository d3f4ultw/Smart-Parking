package mx.smartparking.api.clientes.administracion.modelo;

import java.util.List;

/** Reúne una página de clientes encontrados y los totales de personas, resultados y páginas. */
public record PaginaClientesAdministracion(
        List<ClienteResumenAdministracion> items,
        int pagina,
        int tamanoPagina,
        long totalClientes,
        long totalRegistros,
        int totalPaginas,
        String cursorEventos) {
}
