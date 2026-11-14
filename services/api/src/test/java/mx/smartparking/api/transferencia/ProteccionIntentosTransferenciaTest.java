package mx.smartparking.api.transferencia;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;

class ProteccionIntentosTransferenciaTest {

    @Test
    void bloqueaTrasCincoFallosYSeRecuperaTrasUnMinuto() {
        AtomicReference<Instant> ahora = new AtomicReference<>(Instant.parse("2026-10-23T18:00:00Z"));
        Clock reloj = new Clock() {
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
                return ahora.get();
            }
        };
        ProteccionIntentosTransferencia proteccion = new ProteccionIntentosTransferencia(reloj);

        for (int intento = 0; intento < 5; intento++) {
            assertTrue(proteccion.permitido(ProteccionIntentosTransferencia.Operacion.RECUPERACION, "127.0.0.1"));
            proteccion.registrarFallo(ProteccionIntentosTransferencia.Operacion.RECUPERACION, "127.0.0.1");
        }
        assertFalse(proteccion.permitido(ProteccionIntentosTransferencia.Operacion.RECUPERACION, "127.0.0.1"));

        ahora.set(ahora.get().plus(Duration.ofMinutes(1)));
        assertTrue(proteccion.permitido(ProteccionIntentosTransferencia.Operacion.RECUPERACION, "127.0.0.1"));
        assertTrue(proteccion.permitido(ProteccionIntentosTransferencia.Operacion.RECUPERACION, "127.0.0.2"));
    }

    @Test
    void unExitoLimpiaSoloElContadorDeEsaOperacionYOrigen() {
        ProteccionIntentosTransferencia proteccion = new ProteccionIntentosTransferencia(
                Clock.fixed(Instant.parse("2026-10-23T18:00:00Z"), ZoneOffset.UTC));
        for (int intento = 0; intento < 5; intento++) {
            proteccion.registrarFallo(ProteccionIntentosTransferencia.Operacion.INICIO, "127.0.0.1");
        }
        proteccion.registrarExito(ProteccionIntentosTransferencia.Operacion.INICIO, "127.0.0.1");

        assertTrue(proteccion.permitido(ProteccionIntentosTransferencia.Operacion.INICIO, "127.0.0.1"));
        assertTrue(proteccion.permitido(ProteccionIntentosTransferencia.Operacion.GRANT, "127.0.0.1"));
        assertTrue(proteccion.permitido(ProteccionIntentosTransferencia.Operacion.INICIO, "127.0.0.2"));
    }
}
