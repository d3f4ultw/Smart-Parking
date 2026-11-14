package mx.smartparking.api.seguridad.cliente;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import org.junit.jupiter.api.Test;

class ProteccionIntentosRegistroClienteTest {

    @Test
    void permiteCincoSolicitudesYRespetaElBloqueoCompletoDeQuinceMinutos() {
        RelojControlable reloj = new RelojControlable(Instant.parse("2026-10-26T12:00:00Z"));
        ProteccionIntentosRegistroCliente proteccion = new ProteccionIntentosRegistroCliente(reloj);

        assertTrue(proteccion.admitirSolicitud("correo-hash"));
        reloj.avanzar(Duration.ofMinutes(14));
        assertTrue(proteccion.admitirSolicitud("correo-hash"));
        assertTrue(proteccion.admitirSolicitud("correo-hash"));
        assertTrue(proteccion.admitirSolicitud("correo-hash"));
        assertTrue(proteccion.admitirSolicitud("correo-hash"));

        reloj.avanzar(Duration.ofMinutes(2));
        assertFalse(proteccion.admitirSolicitud("correo-hash"));
        reloj.avanzar(Duration.ofMinutes(13));
        assertTrue(proteccion.admitirSolicitud("correo-hash"));
    }

    private static final class RelojControlable extends Clock {

        private Instant ahora;

        private RelojControlable(Instant ahora) {
            this.ahora = ahora;
        }

        private void avanzar(Duration duracion) {
            ahora = ahora.plus(duracion);
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zona) {
            return this;
        }

        @Override
        public Instant instant() {
            return ahora;
        }
    }
}
