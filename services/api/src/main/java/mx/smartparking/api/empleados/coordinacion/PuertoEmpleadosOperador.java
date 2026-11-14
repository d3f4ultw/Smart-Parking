package mx.smartparking.api.empleados.coordinacion;

import java.util.Optional;

/**
 * Permite consultar y guardar los datos del empleado asociado a una cuenta de operador durante el
 * mismo cambio.
 */
public interface PuertoEmpleadosOperador {

    Optional<EmpleadoEnlaceOperador> bloquearPorId(long empleadoId);

    Optional<EmpleadoEnlaceOperador> consultarPorId(long empleadoId);

    boolean actualizarCorreoYRevision(
            long empleadoId, String correo, String correoNormalizado, long revisionEsperada);

    boolean actualizarEstadoYRevision(long empleadoId, String estado, long revisionEsperada);

    boolean incrementarRevision(long empleadoId, long revisionEsperada);
}
