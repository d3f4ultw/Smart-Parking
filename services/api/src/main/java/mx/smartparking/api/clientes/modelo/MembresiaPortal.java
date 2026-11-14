package mx.smartparking.api.clientes.modelo;

import java.time.Instant;
import mx.smartparking.api.clientes.membresia.modelo.CheckoutPendientePortal;

/**
 * Reúne el estado y las fechas guardadas de la membresía, además de indicar si el cliente puede
 * contratarla.
 */
public record MembresiaPortal(
        EstadoMembresia estado,
        PlanMembresia plan,
        Instant periodoInicio,
        Instant periodoFin,
        Instant siguienteCobroEn,
        boolean cancelacionAlFinal,
        boolean puedeComprar,
        CheckoutPendientePortal checkoutPendiente) {

    public MembresiaPortal(EstadoMembresia estado, PlanMembresia plan) {
        this(estado, plan, null, null, null, false, estado == EstadoMembresia.SIN_MEMBRESIA, null);
    }
}
