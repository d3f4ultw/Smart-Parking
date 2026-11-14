package mx.smartparking.api.eventos;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyEmitter.DataWithMediaType;

/** Comprueba la validación de sesión y el cursor compartido del stream. */
class ServicioEventosAdministracionTest {

    private GestorSesionesPropietario gestorSesiones;
    private RepositorioCuentas cuentas;
    private ServicioEventosAdministracion servicio;
    private MockHttpSession sesion;
    private PrincipalPropietario dueno;
    private AtomicLong reloj;
    private AtomicLong ids;

    @BeforeEach
    void preparar() {
        gestorSesiones = new GestorSesionesPropietario();
        cuentas = mock(RepositorioCuentas.class);
        reloj = new AtomicLong();
        ids = new AtomicLong();
        servicio = new ServicioEventosAdministracion(
                gestorSesiones,
                cuentas,
                reloj::get,
                () -> new UUID(0, ids.incrementAndGet()),
                mock(ScheduledExecutorService.class));
        sesion = new MockHttpSession();
        dueno = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.DUENO, 1, 1, "dueno@example.test");
        gestorSesiones.registrar(sesion, dueno);
        when(cuentas.sesionVigente(
                dueno.cuentaId(), dueno.revisionAcceso(), dueno.rol().name(), dueno.revisionPropietario()))
                .thenReturn(true);
    }

    @AfterEach
    void detener() {
        servicio.detener();
    }

    @Test
    void exigeSesionRegistradaYRolDuenoParaAbrirElStream() {
        ErrorConfiguracion sinPrincipal = assertThrows(
                ErrorConfiguracion.class, () -> servicio.abrirStream(sesion.getId(), null, null));
        ErrorConfiguracion sinSesion = assertThrows(
                ErrorConfiguracion.class, () -> servicio.abrirStream("ausente", dueno, null));

        assertEquals(HttpStatus.FORBIDDEN, sinPrincipal.estadoHttp());
        assertEquals(HttpStatus.UNAUTHORIZED, sinSesion.estadoHttp());
    }

    @Test
    void abreStreamAcotadoYPublicaUnCursorCompartido() {
        SseEmitter emisor = servicio.abrirStream(sesion.getId(), dueno, servicio.cursorActual());
        assertNotNull(emisor);
        assertEquals(ServicioEventosAdministracion.DURACION_EMISOR_MS, emisor.getTimeout());

        String cursorInicial = servicio.cursorActual();
        servicio.publicarDirectorioActualizado();

        assertEquals(0, secuencia(cursorInicial));
        assertEquals(1, secuencia(servicio.cursorActual()));
        verify(cuentas, times(2)).sesionVigente(
                dueno.cuentaId(), dueno.revisionAcceso(), dueno.rol().name(), dueno.revisionPropietario());
    }

    @Test
    void serializaElRegistroYEntregaDeDominiosConcurrentes() throws Exception {
        servicio.abrirStream(sesion.getId(), dueno, servicio.cursorActual());
        CountDownLatch entregandoPrimero = new CountDownLatch(1);
        CountDownLatch liberarPrimero = new CountDownLatch(1);
        CountDownLatch segundoIniciado = new CountDownLatch(1);
        AtomicInteger comprobaciones = new AtomicInteger();
        when(cuentas.sesionVigente(
                dueno.cuentaId(), dueno.revisionAcceso(), dueno.rol().name(), dueno.revisionPropietario()))
                .thenAnswer(invocacion -> {
                    if (comprobaciones.incrementAndGet() == 1) {
                        entregandoPrimero.countDown();
                        if (!liberarPrimero.await(5, TimeUnit.SECONDS)) throw new IllegalStateException("timeout");
                    }
                    return true;
                });
        try (var ejecutor = Executors.newFixedThreadPool(2)) {
            var primero = ejecutor.submit(servicio::publicarVisionActualizada);
            assertTrue(entregandoPrimero.await(5, TimeUnit.SECONDS));
            var segundo = ejecutor.submit(() -> {
                segundoIniciado.countDown();
                servicio.publicarDirectorioActualizado();
            });
            assertTrue(segundoIniciado.await(5, TimeUnit.SECONDS));
            assertThrows(TimeoutException.class, () -> segundo.get(100, TimeUnit.MILLISECONDS));
            assertEquals(1, secuencia(servicio.cursorActual()));
            liberarPrimero.countDown();
            primero.get(5, TimeUnit.SECONDS);
            segundo.get(5, TimeUnit.SECONDS);
            assertEquals(2, secuencia(servicio.cursorActual()));
        } finally {
            liberarPrimero.countDown();
        }
    }

    @Test
    void unFalloDeValidacionCierraElDestinoSinInterrumpirLaPublicacion() {
        servicio.abrirStream(sesion.getId(), dueno, servicio.cursorActual());
        when(cuentas.sesionVigente(
                dueno.cuentaId(), dueno.revisionAcceso(), dueno.rol().name(), dueno.revisionPropietario()))
                .thenThrow(new IllegalStateException("fallo sintético"));
        assertDoesNotThrow(() -> { servicio.publicarVisionActualizada(); });
        assertDoesNotThrow(() -> { servicio.publicarDirectorioActualizado(); });
        assertEquals(2, secuencia(servicio.cursorActual()));
    }

    @Test
    void heartbeatNoMueveCursorNiAgregaCampoSseId() {
        UUID id = id(1);
        var partes = SuscripcionEventosAdministracion.crearEventoHeartbeat(id, 1).build().stream()
                .map(DataWithMediaType::getData)
                .toList();

        assertTrue(partes.stream().anyMatch(parte -> parte instanceof String texto
                && texto.contains("empleado.heartbeat")));
        assertTrue(partes.stream().noneMatch(parte -> parte instanceof String texto
                && texto.startsWith("id:")));
        assertTrue(partes.stream().anyMatch(parte -> Map.of("suscripcionId", id.toString(), "secuencia", 1L)
                .equals(parte)));

        String cursorInicial = servicio.cursorActual();
        servicio.abrirStream(sesion.getId(), dueno, cursorInicial);
        reloj.set(ServicioEventosAdministracion.INTERVALO_HEARTBEAT_NANOS);
        servicio.comprobarConcesiones();

        assertEquals(cursorInicial, servicio.cursorActual());
    }

    @Test
    void ackDeOtraPestanaNoRenuevaElStreamSinConfirmar() {
        UUID idConfirmado = id(2);
        servicio.abrirStream(sesion.getId(), dueno, null);
        servicio.abrirStream(sesion.getId(), dueno, null);
        reloj.set(ServicioEventosAdministracion.INTERVALO_HEARTBEAT_NANOS);
        servicio.comprobarConcesiones();

        servicio.confirmarHeartbeat(sesion.getId(), dueno, idConfirmado.toString(), 2);
        reloj.set(TimeUnit.SECONDS.toNanos(26));
        servicio.comprobarConcesiones();

        for (int indice = 0; indice < 4; indice++) {
            assertNotNull(servicio.abrirStream(sesion.getId(), dueno, null));
        }
        ErrorConfiguracion limite = assertThrows(
                ErrorConfiguracion.class, () -> servicio.abrirStream(sesion.getId(), dueno, null));
        assertEquals(HttpStatus.TOO_MANY_REQUESTS, limite.estadoHttp());
    }

    @Test
    void ackDeOtraSesionNoRenuevaLaConcesion() {
        UUID id = id(1);
        servicio.abrirStream(sesion.getId(), dueno, null);
        MockHttpSession otraSesion = new MockHttpSession();
        gestorSesiones.registrar(otraSesion, dueno);

        servicio.confirmarHeartbeat(otraSesion.getId(), dueno, id.toString(), 1);
        reloj.set(TimeUnit.SECONDS.toNanos(26));
        servicio.comprobarConcesiones();

        for (int indice = 0; indice < 5; indice++) {
            assertNotNull(servicio.abrirStream(sesion.getId(), dueno, null));
        }
    }

    @Test
    void ackAtrasadoRepetidoOFuturoNoRenuevaLaConcesion() {
        UUID id = id(1);
        servicio.abrirStream(sesion.getId(), dueno, null);
        reloj.set(TimeUnit.SECONDS.toNanos(10));
        servicio.comprobarConcesiones();
        servicio.confirmarHeartbeat(sesion.getId(), dueno, id.toString(), 2);

        reloj.set(TimeUnit.SECONDS.toNanos(20));
        servicio.comprobarConcesiones();
        servicio.confirmarHeartbeat(sesion.getId(), dueno, id.toString(), 2);
        servicio.confirmarHeartbeat(sesion.getId(), dueno, id.toString(), 4);
        servicio.confirmarHeartbeat(sesion.getId(), dueno, id.toString(), 3);
        reloj.set(TimeUnit.SECONDS.toNanos(24));
        servicio.confirmarHeartbeat(sesion.getId(), dueno, id.toString(), 3);
        servicio.confirmarHeartbeat(sesion.getId(), dueno, id.toString(), 2);

        reloj.set(TimeUnit.SECONDS.toNanos(46));
        servicio.comprobarConcesiones();
        for (int indice = 0; indice < 5; indice++) {
            assertNotNull(servicio.abrirStream(sesion.getId(), dueno, null));
        }
    }

    private static UUID id(long numero) {
        return new UUID(0, numero);
    }

    private long secuencia(String cursor) {
        return Long.parseLong(cursor.substring(cursor.indexOf(':') + 1));
    }
}
