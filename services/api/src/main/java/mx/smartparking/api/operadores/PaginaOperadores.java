package mx.smartparking.api.operadores;

import java.util.List;

/** Reúne una página de operadores y la cantidad total encontrada en la búsqueda. */
public record PaginaOperadores(
        List<Operador> items,
        int pagina,
        int tamanoPagina,
        long totalRegistros,
        long totalPaginas,
        String cursorEventos) {

    public PaginaOperadores {
        items = List.copyOf(items);
    }
}
