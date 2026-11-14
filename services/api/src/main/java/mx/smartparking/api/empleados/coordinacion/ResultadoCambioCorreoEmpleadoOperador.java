package mx.smartparking.api.empleados.coordinacion;

import java.util.UUID;

/** Indica si cambió el correo del empleado y qué ocurrió con su cuenta de operador vinculada. */
public record ResultadoCambioCorreoEmpleadoOperador(
        String empleadoId, String correo, UUID operadorId, String estadoOperador,
        String revisionEmpleado, String estadoInvitacion) {
}
