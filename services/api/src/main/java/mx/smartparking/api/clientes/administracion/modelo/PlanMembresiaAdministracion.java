package mx.smartparking.api.clientes.administracion.modelo;

/** Describe el plan mensual sin revelar identificadores internos de Stripe. */
public record PlanMembresiaAdministracion(
        String nombre,
        int importeMenorUnidad,
        String moneda,
        String intervalo,
        int intervaloCantidad) {
}
