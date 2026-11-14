package mx.smartparking.api.operadores;

import java.util.UUID;

/** Conserva el resultado de una acción del propietario sobre un empleado para responder igual si se repite. */
public record AccionEmpleadoOperadorPersistida(
        String huellaSolicitud,
        String operacion,
        long empleadoId,
        String estado,
        UUID operadorId,
        String estadoOperador,
        Long revisionEmpleado,
        String estadoEnvio) {
}
