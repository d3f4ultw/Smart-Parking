package mx.smartparking.api.clientes.administracion.persistencia;

import java.util.Optional;

/** Define cómo consultar la lista de clientes y el detalle de cada uno. */
public interface RepositorioClientesAdministracion {

    ResultadoPaginaClientes consultarPagina(int pagina, int tamanoPagina, String filtro, String busqueda);

    Optional<DetalleClientePersistido> consultarDetalle(String codigoPublico);
}
