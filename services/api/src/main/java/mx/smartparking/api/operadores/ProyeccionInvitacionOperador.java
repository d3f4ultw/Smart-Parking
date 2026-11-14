package mx.smartparking.api.operadores;

import java.time.Instant;

/** Reúne el estado de las invitaciones y recuperaciones que el propietario puede consultar. */
public record ProyeccionInvitacionOperador(
        String estadoInvitacion,
        Instant invitacionGeneradaEn,
        Instant invitacionVenceEn,
        Instant invitacionConsumidaEn,
        Instant reenvioDisponibleEn,
        int reemisionesRestantes,
        boolean puedeReemitirInvitacion,
        Instant recuperacionDisponibleEn,
        int recuperacionesRestantes,
        boolean puedeSolicitarRecuperacion) {

    public ProyeccionInvitacionOperador {
        if (reemisionesRestantes < 0 || recuperacionesRestantes < 0) {
            throw new IllegalArgumentException("Los contadores de operación no pueden ser negativos.");
        }
    }
}
