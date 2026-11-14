package mx.smartparking.api.rfid1.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anySet;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;
import mx.smartparking.api.eventos.PublicadorCapturaRfid1;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.SesionPropietarioRevocada;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;

class MantenimientoCapturasRfid1Test {

    private static final Instant AHORA = Instant.parse("2026-10-28T14:00:00Z");
    private static final String HUELLA = "c".repeat(64);

    @Test
    void limpiezaPeriodicaExpiraYReconciliaConSoloHuellasActivas() {
        RepositorioRfid1 repositorio = mock(RepositorioRfid1.class);
        GestorSesionesPropietario sesiones = mock(GestorSesionesPropietario.class);
        AdministradorTransaccionesFalso transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicador = mock(PublicadorCapturaRfid1.class);
        when(sesiones.huellasSesionesActivas()).thenReturn(Set.of(HUELLA));
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(1);
        when(repositorio.invalidarSesionesAusentes(Set.of(HUELLA), AHORA)).thenReturn(0);
        when(repositorio.purgarCapturasTerminalesAnterioresA(AHORA.minusSeconds(86_400))).thenReturn(2);
        doAnswer(invocacion -> {
            assertEquals(1, transacciones.confirmadas);
            return null;
        }).when(publicador).publicarSiActualizada(true);
        var mantenimiento = new MantenimientoCapturasRfid1(
                repositorio, sesiones, transacciones, Clock.fixed(AHORA, ZoneOffset.UTC), publicador);

        mantenimiento.limpiarPeriodicamente();

        verify(sesiones).huellasSesionesActivas();
        verify(repositorio).invalidarSesionesAusentes(Set.of(HUELLA), AHORA);
        assertEquals(1, transacciones.confirmadas);
    }

    @Test
    void revocacionPuntualLimpiaPorHashEnLaTransaccion() {
        RepositorioRfid1 repositorio = mock(RepositorioRfid1.class);
        AdministradorTransaccionesFalso transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicador = mock(PublicadorCapturaRfid1.class);
        when(repositorio.invalidarPorSesion(HUELLA, AHORA)).thenReturn(1);
        doAnswer(invocacion -> {
            assertEquals(1, transacciones.confirmadas);
            return null;
        }).when(publicador).publicarSiActualizada(true);
        var mantenimiento = new MantenimientoCapturasRfid1(
                repositorio, mock(GestorSesionesPropietario.class), transacciones,
                Clock.fixed(AHORA, ZoneOffset.UTC), publicador);

        mantenimiento.invalidarSesionRevocada(new SesionPropietarioRevocada(HUELLA));

        verify(repositorio).invalidarPorSesion(HUELLA, AHORA);
        verify(publicador).publicarSiActualizada(true);
        assertEquals(1, transacciones.confirmadas);
    }

    @Test
    void limiteSeTomaAntesDelSnapshotYNoInvalidaCapturaCreadaDespues() {
        RepositorioRfid1 repositorio = mock(RepositorioRfid1.class);
        GestorSesionesPropietario sesiones = mock(GestorSesionesPropietario.class);
        AdministradorTransaccionesFalso transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicador = mock(PublicadorCapturaRfid1.class);
        RelojCarrera reloj = new RelojCarrera(AHORA);
        AtomicReference<Instant> creadaEn = new AtomicReference<>();
        when(sesiones.huellasSesionesActivas()).thenAnswer(invocacion -> {
            creadaEn.set(reloj.instanteDeCapturaPosteriorAlSnapshot());
            return Set.of(HUELLA);
        });
        when(repositorio.expirarCapturasVencidas(any(Instant.class))).thenReturn(0);
        when(repositorio.invalidarSesionesAusentes(anySet(), any(Instant.class))).thenAnswer(invocacion -> {
            Instant limite = invocacion.getArgument(1);
            return creadaEn.get().isBefore(limite) ? 1 : 0;
        });
        when(repositorio.purgarCapturasTerminalesAnterioresA(any(Instant.class))).thenReturn(0);
        var mantenimiento = new MantenimientoCapturasRfid1(
                repositorio, sesiones, transacciones, reloj, publicador);

        mantenimiento.limpiarPeriodicamente();

        verify(repositorio).invalidarSesionesAusentes(Set.of(HUELLA), AHORA);
        verify(publicador).publicarSiActualizada(false);
        assertEquals(AHORA.plusSeconds(3), creadaEn.get());
        assertEquals(1, transacciones.confirmadas);
    }

    @Test
    void capturaCreadaExactamenteEnElLimiteNoSeInvalida() {
        RepositorioRfid1 repositorio = mock(RepositorioRfid1.class);
        GestorSesionesPropietario sesiones = mock(GestorSesionesPropietario.class);
        AdministradorTransaccionesFalso transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicador = mock(PublicadorCapturaRfid1.class);
        Instant creadaEn = AHORA;
        when(sesiones.huellasSesionesActivas()).thenReturn(Set.of(HUELLA));
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0);
        when(repositorio.invalidarSesionesAusentes(Set.of(HUELLA), AHORA)).thenAnswer(invocacion ->
                creadaEn.isBefore(invocacion.getArgument(1)) ? 1 : 0);
        when(repositorio.purgarCapturasTerminalesAnterioresA(AHORA.minusSeconds(86_400))).thenReturn(0);
        var mantenimiento = new MantenimientoCapturasRfid1(
                repositorio, sesiones, transacciones, Clock.fixed(AHORA, ZoneOffset.UTC), publicador);

        mantenimiento.limpiarPeriodicamente();

        verify(publicador).publicarSiActualizada(false);
        assertEquals(1, transacciones.confirmadas);
    }

    private static final class AdministradorTransaccionesFalso implements PlatformTransactionManager {
        private int confirmadas;

        @Override
        public TransactionStatus getTransaction(TransactionDefinition definicion) {
            return new SimpleTransactionStatus();
        }

        @Override
        public void commit(TransactionStatus estado) {
            confirmadas++;
        }

        @Override
        public void rollback(TransactionStatus estado) {
            throw new AssertionError("No se esperaba rollback en esta prueba.");
        }
    }

    private static final class RelojCarrera extends Clock {
        private Instant actual;

        private RelojCarrera(Instant inicio) {
            actual = inicio;
        }

        @Override
        public Instant instant() {
            Instant instante = actual;
            actual = actual.plusSeconds(2);
            return instante;
        }

        private Instant instanteDeCapturaPosteriorAlSnapshot() {
            Instant instante = actual.plusSeconds(1);
            actual = actual.plusSeconds(2);
            return instante;
        }

        @Override
        public ZoneOffset getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(java.time.ZoneId zona) {
            return this;
        }
    }
}
