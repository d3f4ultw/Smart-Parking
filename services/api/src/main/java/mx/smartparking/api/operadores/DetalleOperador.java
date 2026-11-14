package mx.smartparking.api.operadores;

import java.time.Instant;
import java.util.UUID;

/** Reúne la información y las acciones que el propietario puede ver al administrar un operador. */
public record DetalleOperador(
        UUID id,
        String nombres,
        String primerApellido,
        String segundoApellido,
        String correo,
        EstadoCuentaOperador estado,
        String estadoInvitacion,
        Instant invitacionGeneradaEn,
        Instant invitacionVenceEn,
        Instant invitacionConsumidaEn,
        Instant creadaEn,
        Instant reenvioDisponibleEn,
        int reemisionesRestantes,
        boolean puedeReemitirInvitacion,
        Instant recuperacionDisponibleEn,
        int recuperacionesRestantes,
        boolean puedeSolicitarRecuperacion,
        boolean puedeDesactivar,
        boolean puedeReactivar,
        String empleadoIdTexto,
        String estadoConciliacion) {

    public DetalleOperador(
            UUID id,
            String nombres,
            String primerApellido,
            String segundoApellido,
            String correo,
            EstadoCuentaOperador estado,
            String estadoInvitacion,
            Instant invitacionGeneradaEn,
            Instant invitacionVenceEn,
            Instant invitacionConsumidaEn,
            Instant creadaEn,
            Instant reenvioDisponibleEn,
            int reemisionesRestantes,
            boolean puedeReemitirInvitacion,
            Instant recuperacionDisponibleEn,
            int recuperacionesRestantes,
            boolean puedeSolicitarRecuperacion,
            boolean puedeDesactivar,
            boolean puedeReactivar) {
        this(id, nombres, primerApellido, segundoApellido, correo, estado, estadoInvitacion,
                invitacionGeneradaEn, invitacionVenceEn, invitacionConsumidaEn, creadaEn,
                reenvioDisponibleEn, reemisionesRestantes, puedeReemitirInvitacion,
                recuperacionDisponibleEn, recuperacionesRestantes, puedeSolicitarRecuperacion,
                puedeDesactivar, puedeReactivar, null, "LEGADO_SIN_VINCULO");
    }
}
