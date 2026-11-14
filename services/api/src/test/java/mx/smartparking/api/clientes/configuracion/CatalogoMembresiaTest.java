package mx.smartparking.api.clientes.configuracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

class CatalogoMembresiaTest {

    @Test
    void conservaElCatalogoAcordadoComoConfiguracionTipada() {
        CatalogoMembresia catalogo = new CatalogoMembresia(
                "prod_VTMowkF8XuDWIR", "price_1USQ5HAqtHmR2qmyAWwUp5vy",
                "Smart Parking - Membresía Mensual", 39_900, "MXN", "month", 1);

        assertEquals("MXN", catalogo.moneda());
        assertEquals("month", catalogo.intervalo());
    }

    @Test
    void rechazaUnImporteQueNoCoincideConElContrato() {
        assertThrows(IllegalArgumentException.class, () -> new CatalogoMembresia(
                "prod_VTMowkF8XuDWIR", "price_1USQ5HAqtHmR2qmyAWwUp5vy",
                "Smart Parking - Membresía Mensual", 40_000, "MXN", "month", 1));
    }
}
