package mx.smartparking.api.activacion;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import org.junit.jupiter.api.Test;

class ProteccionIntentosActivacionTest {

    private static final Instant AHORA = Instant.parse("2026-10-25T18:00:00Z");

    @Test
    void bloqueaEnElQuintoFalloYSeLiberaAlCumplirQuinceMinutos() {
        RelojAjustable reloj = new RelojAjustable(AHORA);
        ProteccionIntentosActivacion proteccion = new ProteccionIntentosActivacion(reloj);
        String hashToken = "hash-token-de-prueba";

        assertTrue(proteccion.permitido(hashToken));
        for (int intento = 0; intento < 5; intento++) {
            proteccion.registrarFallo(hashToken);
        }
        assertFalse(proteccion.permitido(hashToken));

        reloj.avanzar(java.time.Duration.ofMinutes(15).minusSeconds(1));
        assertFalse(proteccion.permitido(hashToken));
        reloj.avanzar(java.time.Duration.ofSeconds(1));
        assertTrue(proteccion.permitido(hashToken));
    }

    private static final class RelojAjustable extends Clock {

        private Instant ahora;

        private RelojAjustable(Instant ahora) {
            this.ahora = ahora;
        }

        private void avanzar(java.time.Duration duracion) {
            ahora = ahora.plus(duracion);
        }

        @Override
        public Instant instant() {
            return ahora;
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }
    }
}
