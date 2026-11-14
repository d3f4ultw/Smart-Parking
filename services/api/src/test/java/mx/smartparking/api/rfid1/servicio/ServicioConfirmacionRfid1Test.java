package mx.smartparking.api.rfid1.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.PublicadorCapturaRfid1;
import mx.smartparking.api.eventos.PublicadorTarjetasRfid1;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.ResultadoConfirmacionRfid1;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.VistaPreviaRfid1Persistida;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;

class ServicioConfirmacionRfid1Test {

    private static final Instant AHORA = Instant.parse("2026-10-28T14:00:00Z");
    private static final String CAPTURA = "00112233445566778899aabbccddeeff";
    private static final String HUELLA = "a".repeat(64);
    private static final String CLAVE = "clave-confirmacion-persistente-01";
    private static final PrincipalPropietario DUENO = new PrincipalPropietario(
            UUID.fromString("d6a191d4-27e4-48a3-82af-4d5e69c9bfbd"), RolCuenta.DUENO, 3, 8, "dueno@test.invalid");

    @Test
    void vistaPreviaQuedaVinculadaAPropietarioRevisionesYHuella() {
        RepositorioRfid1 repositorio = mock(RepositorioRfid1.class);
        var transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicador = mock(PublicadorCapturaRfid1.class);
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0);
        when(repositorio.consultarVistaPrevia(CAPTURA, DUENO.cuentaId(), 3, 8, HUELLA, AHORA))
                .thenReturn(Optional.of(new VistaPreviaRfid1Persistida(
                        "04A1B2C3", AHORA, AHORA.plusSeconds(300))));
        var servicio = servicio(repositorio, transacciones, publicador, mock(PublicadorTarjetasRfid1.class));

        var previa = servicio.consultarVistaPrevia(CAPTURA, HUELLA, DUENO);

        assertEquals("04A1B2C3", previa.uid());
        assertEquals(AHORA.plusSeconds(300), previa.confirmacionVenceEn());
        verify(repositorio).consultarVistaPrevia(CAPTURA, DUENO.cuentaId(), 3, 8, HUELLA, AHORA);
        verify(publicador).publicarSiActualizada(false);
        assertEquals(1, transacciones.confirmadas);
    }

    @Test
    void confirmarEsIdempotenteYPublicaSoloLaPrimeraAsociacionTrasCommit() {
        RepositorioRfid1 repositorio = mock(RepositorioRfid1.class);
        var transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicadorCapturas = mock(PublicadorCapturaRfid1.class);
        PublicadorTarjetasRfid1 publicadorTarjetas = mock(PublicadorTarjetasRfid1.class);
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0, 0);
        when(repositorio.confirmarCaptura(CAPTURA, DUENO.cuentaId(), 3, 8, HUELLA, ClavesRfid1.hashClave(CLAVE), AHORA))
                .thenReturn(new ResultadoConfirmacionRfid1("COMPLETADA", 71L, null, false),
                        new ResultadoConfirmacionRfid1("COMPLETADA", 71L, null, true));
        doAnswer(invocacion -> {
            assertEquals(1, transacciones.confirmadas);
            return null;
        }).when(publicadorTarjetas).publicarSiActualizadas(true);
        var servicio = servicio(repositorio, transacciones, publicadorCapturas, publicadorTarjetas);

        var primera = servicio.confirmar(CAPTURA, HUELLA, CLAVE, DUENO);
        var repetida = servicio.confirmar(CAPTURA, HUELLA, CLAVE, DUENO);

        assertEquals(71, primera.asociacionId());
        assertEquals(71, repetida.asociacionId());
        verify(repositorio, org.mockito.Mockito.times(2)).confirmarCaptura(
                CAPTURA, DUENO.cuentaId(), 3, 8, HUELLA, ClavesRfid1.hashClave(CLAVE), AHORA);
        verify(publicadorCapturas).publicarSiActualizada(true);
        verify(publicadorCapturas).publicarSiActualizada(false);
        verify(publicadorTarjetas).publicarSiActualizadas(true);
        verify(publicadorTarjetas).publicarSiActualizadas(false);
        assertEquals(2, transacciones.confirmadas);
    }

    @Test
    void conflictoPorUidNoConfirmaYConservaLaCapturaActiva() {
        RepositorioRfid1 repositorio = mock(RepositorioRfid1.class);
        var transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicadorCapturas = mock(PublicadorCapturaRfid1.class);
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0);
        when(repositorio.confirmarCaptura(CAPTURA, DUENO.cuentaId(), 3, 8, HUELLA, ClavesRfid1.hashClave(CLAVE), AHORA))
                .thenReturn(new ResultadoConfirmacionRfid1("ESCANEANDO", null, "TARJETA_YA_REGISTRADA", false));
        doAnswer(invocacion -> {
            assertEquals(1, transacciones.confirmadas);
            return null;
        }).when(publicadorCapturas).publicarSiActualizada(true);
        var servicio = servicio(repositorio, transacciones, publicadorCapturas, mock(PublicadorTarjetasRfid1.class));

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.confirmar(CAPTURA, HUELLA, CLAVE, DUENO));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertEquals("TARJETA_YA_REGISTRADA", error.codigo());
        assertEquals(1, transacciones.confirmadas);
    }

    @Test
    void clienteSinMembresiaRecibeUnConflictoClaroAlConfirmar() {
        RepositorioRfid1 repositorio = mock(RepositorioRfid1.class);
        var transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicadorCapturas = mock(PublicadorCapturaRfid1.class);
        PublicadorTarjetasRfid1 publicadorTarjetas = mock(PublicadorTarjetasRfid1.class);
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0);
        when(repositorio.confirmarCaptura(CAPTURA, DUENO.cuentaId(), 3, 8, HUELLA,
                ClavesRfid1.hashClave(CLAVE), AHORA))
                .thenReturn(new ResultadoConfirmacionRfid1("CANCELADA", null, "CLIENTE_SIN_MEMBRESIA", false));
        doAnswer(invocacion -> {
            assertEquals(1, transacciones.confirmadas);
            return null;
        }).when(publicadorCapturas).publicarSiActualizada(true);
        var servicio = servicio(repositorio, transacciones, publicadorCapturas, publicadorTarjetas);

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.confirmar(CAPTURA, HUELLA, CLAVE, DUENO));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertEquals("CLIENTE_SIN_MEMBRESIA", error.codigo());
        assertTrue(error.getMessage().contains("sin membresía"));
        verify(publicadorCapturas).publicarSiActualizada(true);
        verify(publicadorTarjetas).publicarSiActualizadas(false);
        assertEquals(1, transacciones.confirmadas);
    }

    @Test
    void operadorConfirmaSoloLaCapturaLigadaASuCuentaYPublicaLaCancelacionPorModo() {
        PrincipalPropietario operador = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.OPERADOR, 6, 0, "operador@test.invalid");
        RepositorioRfid1 repositorio = mock(RepositorioRfid1.class);
        var transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicadorCapturas = mock(PublicadorCapturaRfid1.class);
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0);
        when(repositorio.confirmarCaptura(CAPTURA, operador.cuentaId(), 6, 1, HUELLA,
                ClavesRfid1.hashClave(CLAVE), AHORA))
                .thenReturn(new ResultadoConfirmacionRfid1("CANCELADA", null, "CAPTURA_NO_VIGENTE", false));
        doAnswer(invocacion -> {
            assertEquals(1, transacciones.confirmadas);
            return null;
        }).when(publicadorCapturas).publicarSiActualizada(true);
        var servicio = servicio(repositorio, transacciones, publicadorCapturas, mock(PublicadorTarjetasRfid1.class));

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.confirmar(CAPTURA, HUELLA, CLAVE, operador));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertEquals("CAPTURA_NO_VIGENTE", error.codigo());
        verify(repositorio).confirmarCaptura(CAPTURA, operador.cuentaId(), 6, 1, HUELLA,
                ClavesRfid1.hashClave(CLAVE), AHORA);
        verify(publicadorCapturas).publicarSiActualizada(true);
        assertEquals(1, transacciones.confirmadas);
    }

    @Test
    void vistaPreviaDeOperadorUsaMarcadorInternoSinCambiarSuRevisionDeSesion() {
        PrincipalPropietario operador = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.OPERADOR, 6, 0, "operador@test.invalid");
        RepositorioRfid1 repositorio = mock(RepositorioRfid1.class);
        var transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicadorCapturas = mock(PublicadorCapturaRfid1.class);
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0);
        when(repositorio.consultarVistaPrevia(CAPTURA, operador.cuentaId(), 6, 1, HUELLA, AHORA))
                .thenReturn(Optional.of(new VistaPreviaRfid1Persistida(
                        "04A1B2C3", AHORA, AHORA.plusSeconds(300))));
        var servicio = servicio(repositorio, transacciones, publicadorCapturas, mock(PublicadorTarjetasRfid1.class));

        var previa = servicio.consultarVistaPrevia(CAPTURA, HUELLA, operador);

        assertEquals("04A1B2C3", previa.uid());
        verify(repositorio).consultarVistaPrevia(CAPTURA, operador.cuentaId(), 6, 1, HUELLA, AHORA);
        verify(publicadorCapturas).publicarSiActualizada(false);
        assertEquals(1, transacciones.confirmadas);
    }

    private static ServicioConfirmacionRfid1 servicio(
            RepositorioRfid1 repositorio,
            AdministradorTransaccionesFalso transacciones,
            PublicadorCapturaRfid1 publicadorCapturas,
            PublicadorTarjetasRfid1 publicadorTarjetas) {
        return new ServicioConfirmacionRfid1(
                repositorio, transacciones, Clock.fixed(AHORA, ZoneOffset.UTC), publicadorCapturas, publicadorTarjetas);
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
}
