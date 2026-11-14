package mx.smartparking.api.rfid1.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;

class ServicioEstadoConexionRfid1Test {

    private static final Instant AHORA = Instant.parse("2026-10-29T12:00:00Z");

    @Test
    void sinHeartbeatElEstadoEsDesconocido() {
        ServicioEstadoConexionRfid1 servicio = new ServicioEstadoConexionRfid1(new RelojMutable(AHORA));

        var estado = servicio.consultar();

        assertEquals("DESCONOCIDO", estado.estado());
        assertNull(estado.actualizadoEn());
    }

    @Test
    void heartbeatVenceSoloDespuesDeVeinteSegundos() {
        RelojMutable reloj = new RelojMutable(AHORA);
        ServicioEstadoConexionRfid1 servicio = new ServicioEstadoConexionRfid1(reloj);
        servicio.registrar(true);

        reloj.avanzar(Duration.ofSeconds(20));
        assertEquals("CONECTADO", servicio.consultar().estado());

        reloj.avanzar(Duration.ofNanos(1));
        var vencido = servicio.consultar();
        assertEquals("DESCONECTADO", vencido.estado());
        assertEquals(AHORA, vencido.actualizadoEn());

        servicio.registrar(true);
        assertEquals("CONECTADO", servicio.consultar().estado());
    }

    @Test
    void servicioNuevoTrasReinicioNoConservaElHeartbeatEnMemoria() {
        RelojMutable reloj = new RelojMutable(AHORA);
        ServicioEstadoConexionRfid1 anterior = new ServicioEstadoConexionRfid1(reloj);
        anterior.registrar(true);

        ServicioEstadoConexionRfid1 reiniciado = new ServicioEstadoConexionRfid1(reloj);

        assertEquals("CONECTADO", anterior.consultar().estado());
        assertEquals("DESCONOCIDO", reiniciado.consultar().estado());
        assertNull(reiniciado.consultar().actualizadoEn());
    }

    @Test
    void heartbeatDesconectadoSeReflejaDeInmediato() {
        ServicioEstadoConexionRfid1 servicio = new ServicioEstadoConexionRfid1(new RelojMutable(AHORA));

        servicio.registrar(false);

        assertEquals("DESCONECTADO", servicio.consultar().estado());
        assertEquals(AHORA, servicio.consultar().actualizadoEn());
    }

    private static final class RelojMutable extends Clock {
        private final AtomicReference<Instant> ahora;
        private final ZoneId zona;

        private RelojMutable(Instant inicio) {
            this(new AtomicReference<>(inicio), ZoneOffset.UTC);
        }

        private RelojMutable(AtomicReference<Instant> ahora, ZoneId zona) {
            this.ahora = ahora;
            this.zona = zona;
        }

        @Override
        public ZoneId getZone() {
            return zona;
        }

        @Override
        public Clock withZone(ZoneId nuevaZona) {
            return new RelojMutable(ahora, nuevaZona);
        }

        @Override
        public Instant instant() {
            return ahora.get();
        }

        private void avanzar(Duration duracion) {
            ahora.updateAndGet(instante -> instante.plus(duracion));
        }
    }
}
