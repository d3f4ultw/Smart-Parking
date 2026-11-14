package mx.smartparking.api.seguridad;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import org.junit.jupiter.api.Test;

class ProteccionIntentosInicioSesionTest {

    @Test
    void bloqueaTrasCincoFallosYSeLiberaConLoginCorrecto() {
        ProteccionIntentosInicioSesion proteccion = new ProteccionIntentosInicioSesion(
                Clock.fixed(Instant.parse("2026-10-23T12:00:00Z"), ZoneId.of("UTC")));

        for (int intento = 0; intento < 5; intento++) {
            proteccion.registrarFallo("correo-hasheado");
        }

        assertTrue(proteccion.estaBloqueado("correo-hasheado"));
        proteccion.registrarExito("correo-hasheado");
        assertFalse(proteccion.estaBloqueado("correo-hasheado"));
    }
}
