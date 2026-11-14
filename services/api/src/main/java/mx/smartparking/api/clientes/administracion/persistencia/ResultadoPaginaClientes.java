package mx.smartparking.api.clientes.administracion.persistencia;

import java.util.List;

/** Reúne una página de clientes encontrados y la cantidad total para mostrar los resultados. */
public record ResultadoPaginaClientes(
        List<ClienteFilaPersistido> items,
        int pagina,
        long totalClientes,
        long totalRegistros,
        int totalPaginas) {

    public ResultadoPaginaClientes {
        items = List.copyOf(items);
    }
}
