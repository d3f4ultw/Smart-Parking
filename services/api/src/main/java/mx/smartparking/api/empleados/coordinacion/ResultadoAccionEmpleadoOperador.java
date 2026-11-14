package mx.smartparking.api.empleados.coordinacion;

import java.util.UUID;

/** Reúne el resultado de cambiar el acceso de un operador sin mostrar datos secretos. */
public record ResultadoAccionEmpleadoOperador(
        String empleadoId, UUID operadorId, String estadoOperador,
        String revisionEmpleado, String estadoInvitacion) {
}
