package mx.smartparking.api.persistencia;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.empleados.Empleado;
import mx.smartparking.api.empleados.EstadoEmpleado;

/** Define cómo consultar empleados y guardar un registro sin duplicarlo si se repite la solicitud. */
public interface RepositorioEmpleados {

    ResultadoPaginaEmpleados consultarPagina(int paginaSolicitada, int tamanoPagina);

    ResultadoPaginaEmpleados consultarElegiblesParaOperador(
            int paginaSolicitada, int tamanoPagina, String busqueda);

    boolean reservarRegistro(UUID cuentaId, String claveHash, String huellaSolicitud);

    Optional<ComprobanteRegistroEmpleado> buscarComprobante(UUID cuentaId, String claveHash);

    long crearEmpleado(
            String nombres,
            String primerApellido,
            String segundoApellido,
            String correo,
            String correoNormalizado);

    void completarRegistro(UUID cuentaId, String claveHash, long empleadoId);

    Optional<Empleado> obtener(long id);

    Optional<Empleado> bloquearPorId(long id);

    Empleado actualizarEstado(long id, EstadoEmpleado estado, long revision);

    record ResultadoPaginaEmpleados(
            List<Empleado> items,
            int pagina,
            long totalRegistros,
            long totalPaginas) {
    }

    record ComprobanteRegistroEmpleado(String huellaSolicitud, String estado, Long empleadoId) {
    }
}
