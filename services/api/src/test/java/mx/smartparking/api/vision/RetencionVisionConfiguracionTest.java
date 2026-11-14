package mx.smartparking.api.vision;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;

import java.time.Clock;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

/** La ventana debe cubrir la edad admitida y la cuota debe ser finita. */
class RetencionVisionConfiguracionTest {
    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);

    @Test
    void rechazaVentanaInferiorALaEdadAdmitidaYCuotasFueraDelRango() {
        assertThrows(IllegalArgumentException.class,
                () -> new ServicioVision(jdbc, Clock.systemUTC(), 45, 15, 3, 18, 4096));
        assertThrows(IllegalArgumentException.class,
                () -> new ServicioVision(jdbc, Clock.systemUTC(), 45, 15, 3, 300, 1));
        assertThrows(IllegalArgumentException.class,
                () -> new ServicioVision(jdbc, Clock.systemUTC(), 45, 15, 3, 300, 100_001));
        assertDoesNotThrow(() -> new ServicioVision(jdbc, Clock.systemUTC(), 45, 15, 3, 19, 2));
    }

    @Test
    void rechazaIntervalosDeLimpiezaQueNoSonOperables() {
        ServicioVision servicio = mock(ServicioVision.class);
        assertThrows(IllegalArgumentException.class, () -> new MantenimientoRecibosVision(jdbc, servicio, 999));
        assertThrows(IllegalArgumentException.class, () -> new MantenimientoRecibosVision(jdbc, servicio, 3_600_001));
        assertDoesNotThrow(() -> new MantenimientoRecibosVision(jdbc, servicio, 30_000));
    }
}
