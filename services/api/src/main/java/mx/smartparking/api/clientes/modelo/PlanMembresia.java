package mx.smartparking.api.clientes.modelo;

/** Describe el plan de membresía que el cliente puede consultar en su cuenta. */
public record PlanMembresia(
        String productoId,
        String precioId,
        String nombre,
        int importeMenorUnidad,
        String moneda,
        String intervalo,
        int intervaloCantidad) {
}
