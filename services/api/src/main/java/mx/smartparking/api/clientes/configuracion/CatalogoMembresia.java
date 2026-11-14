 package mx.smartparking.api.clientes.configuracion;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Reúne los datos del plan de membresía mensual y comprueba que su nombre, precio y frecuencia sean
 * los permitidos antes de usarlos en el portal del cliente.
 */
@ConfigurationProperties(prefix = "smartparking.clientes.membresia")
public record CatalogoMembresia(
        String productoId,
        String precioId,
        String nombre,
        int importeMenorUnidad,
        String moneda,
        String intervalo,
        int intervaloCantidad) {

    private static final String PRODUCTO_ACORDADO = "prod_VTMowkF8XuDWIR";
    private static final String PRECIO_ACORDADO = "price_1USQ5HAqtHmR2qmyAWwUp5vy";
    private static final String NOMBRE_ACORDADO = "Smart Parking - Membresía Mensual";

    public CatalogoMembresia {
        exigir(PRODUCTO_ACORDADO.equals(productoId) && productoId.matches("prod_[A-Za-z0-9]+"),
                "El identificador del producto de membresía no es válido.");
        exigir(PRECIO_ACORDADO.equals(precioId) && precioId.matches("price_[A-Za-z0-9]+"),
                "El identificador del precio de membresía no es válido.");
        exigir(NOMBRE_ACORDADO.equals(nombre) && nombre.codePointCount(0, nombre.length()) <= 120,
                "El nombre del plan de membresía no es válido.");
        exigir(importeMenorUnidad == 39_900, "El importe del plan de membresía no coincide con el contrato.");
        exigir("MXN".equals(moneda), "La moneda del plan de membresía no coincide con el contrato.");
        exigir("month".equals(intervalo), "El intervalo del plan de membresía no coincide con el contrato.");
        exigir(intervaloCantidad == 1, "La cantidad del intervalo de membresía no es válida.");
    }

    private static void exigir(boolean condicion, String mensaje) {
        if (!condicion) {
            throw new IllegalArgumentException(mensaje);
        }
    }
}
