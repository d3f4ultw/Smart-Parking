package mx.smartparking.api.activacion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.correo.NotificadorInvitacionOperador;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.persistencia.AccionOperadorPersistida;
import mx.smartparking.api.persistencia.CuentaActivacionOperador;
import mx.smartparking.api.persistencia.InvitacionOperadorPersistida;
import mx.smartparking.api.persistencia.RepositorioAccionesOperador;
import mx.smartparking.api.persistencia.RepositorioActivacionOperador;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;

class ServicioAdministracionInvitacionesOperadorTest {

    private static final Instant AHORA = Instant.parse("2026-10-25T18:00:00Z");
    private static final UUID OPERADOR_ID = UUID.fromString("ae51f643-a8ec-48ae-b682-53060dbf2e69");
    private static final String CLAVE = "idempotencia-operador-0001";
    private static final String ORIGEN = "https://parking.example.test";

    @Test
    void replayIdempotenteNoVuelveAEnviarNiReemplazaElToken() {
        RepositorioActivacionOperador cuentas = mock(RepositorioActivacionOperador.class);
        RepositorioAccionesOperador acciones = mock(RepositorioAccionesOperador.class);
        ServicioActivacionOperador activacion = mock(ServicioActivacionOperador.class);
        NotificadorInvitacionOperador notificador = mock(NotificadorInvitacionOperador.class);
        ServicioEventosAdministracion eventos = mock(ServicioEventosAdministracion.class);
        ServicioAdministracionInvitacionesOperador servicio = servicio(
                cuentas, acciones, activacion, notificador, eventos, new ArrayList<>());
        invitacionExistente(cuentas, acciones);
        when(acciones.bloquearAccion(OPERADOR_ID, "REEMITIR_INVITACION", SeguridadTokensOperador.hash(CLAVE)))
                .thenReturn(Optional.of(new AccionOperadorPersistida("REEMITIR_INVITACION", AHORA,
                        EstadoEnvioInvitacion.ENVIADO, 4L, AHORA.plusSeconds(7200))));
        when(acciones.consultarInvitacion(OPERADOR_ID)).thenReturn(Optional.of(invitacion(AHORA.minusSeconds(10))));
        when(acciones.contarAcciones(eq(OPERADOR_ID), anyString(), any(Instant.class)))
                .thenAnswer(llamada -> "REEMITIR_INVITACION".equals(llamada.getArgument(1)) ? 1 : 0);
        when(acciones.ultimaAccion(eq(OPERADOR_ID), anyString())).thenReturn(Optional.empty());

        ResultadoReemisionInvitacionOperador resultado = servicio.reemitir(OPERADOR_ID, "\"4\"", CLAVE);

        assertEquals(EstadoEnvioInvitacion.ENVIADO, resultado.respuesta().estadoInvitacion());
        assertFalse(resultado.respuesta().puedeReemitirInvitacion());
        assertEquals(4L, resultado.revisionAcceso());
        verify(acciones, never()).reemplazarInvitacion(any(), anyString(), anyString(), any(), any(), any());
        verify(notificador, never()).enviar(anyString(), anyString());
        verify(eventos, never()).publicarDirectorioOperadorActualizado();
    }

    @Test
    void persisteFalloSmtpDespuesDelCommitYMantieneLaRespuesta() {
        List<String> orden = new ArrayList<>();
        RepositorioActivacionOperador cuentas = mock(RepositorioActivacionOperador.class);
        RepositorioAccionesOperador acciones = mock(RepositorioAccionesOperador.class);
        ServicioActivacionOperador activacion = mock(ServicioActivacionOperador.class);
        NotificadorInvitacionOperador notificador = mock(NotificadorInvitacionOperador.class);
        ServicioEventosAdministracion eventos = mock(ServicioEventosAdministracion.class);
        ServicioAdministracionInvitacionesOperador servicio = servicio(
                cuentas, acciones, activacion, notificador, eventos, orden);
        invitacionExistente(cuentas, acciones, AHORA.minusSeconds(61));
        when(acciones.bloquearAccion(OPERADOR_ID, "REEMITIR_INVITACION", SeguridadTokensOperador.hash(CLAVE)))
                .thenReturn(Optional.empty());
        when(acciones.contarAcciones(eq(OPERADOR_ID), anyString(), any(Instant.class))).thenReturn(0);
        when(acciones.reemplazarInvitacion(eq(OPERADOR_ID), anyString(), anyString(), any(), any(), any()))
                .thenReturn(true);
        when(acciones.insertarAccion(eq(OPERADOR_ID), eq("REEMITIR_INVITACION"), anyString(), any(),
                eq(EstadoEnvioInvitacion.ENVIANDO), eq(4L), any())).thenReturn(true);
        when(acciones.actualizarEstadoInvitacion(eq(OPERADOR_ID), anyString(), eq(EstadoEnvioInvitacion.FALLIDO)))
                .thenReturn(true);
        when(acciones.consultarInvitacion(OPERADOR_ID))
                .thenReturn(Optional.of(invitacion(AHORA, EstadoEnvioInvitacion.FALLIDO)));
        when(acciones.ultimaAccion(eq(OPERADOR_ID), anyString())).thenReturn(Optional.empty());
        when(notificador.estaHabilitado()).thenReturn(true);
        when(notificador.enviar(eq("operador@example.test"), anyString())).thenAnswer(llamada -> {
            assertTrue(orden.contains("commit"));
            orden.add("smtp");
            assertTrue(((String) llamada.getArgument(1)).startsWith(ORIGEN + "/activar-operador#"));
            return EstadoEnvioInvitacion.FALLIDO;
        });

        ResultadoReemisionInvitacionOperador resultado = servicio.reemitir(OPERADOR_ID, "\"4\"", CLAVE);

        assertEquals(EstadoEnvioInvitacion.FALLIDO, resultado.respuesta().estadoInvitacion());
        assertEquals(List.of("commit", "sse", "smtp", "commit", "sse"), orden);
        verify(acciones).actualizarEstadoAccion(
                OPERADOR_ID, "REEMITIR_INVITACION", SeguridadTokensOperador.hash(CLAVE), EstadoEnvioInvitacion.FALLIDO);
    }

    @Test
    void enfriamientoDevuelveEsperaPrecisaSinEnviarCorreo() {
        RepositorioActivacionOperador cuentas = mock(RepositorioActivacionOperador.class);
        RepositorioAccionesOperador acciones = mock(RepositorioAccionesOperador.class);
        ServicioActivacionOperador activacion = mock(ServicioActivacionOperador.class);
        NotificadorInvitacionOperador notificador = mock(NotificadorInvitacionOperador.class);
        ServicioEventosAdministracion eventos = mock(ServicioEventosAdministracion.class);
        ServicioAdministracionInvitacionesOperador servicio = servicio(
                cuentas, acciones, activacion, notificador, eventos, new ArrayList<>());
        invitacionExistente(cuentas, acciones, AHORA.minusSeconds(10));
        when(acciones.bloquearAccion(OPERADOR_ID, "REEMITIR_INVITACION", SeguridadTokensOperador.hash(CLAVE)))
                .thenReturn(Optional.empty());

        ErrorLimitacionAccionOperador error = assertThrows(ErrorLimitacionAccionOperador.class,
                () -> servicio.reemitir(OPERADOR_ID, "\"4\"", CLAVE));

        assertEquals("REENVIO_EN_ENFRIAMIENTO", error.codigo());
        assertEquals(50L, error.retryAfterSeconds());
        verify(notificador, never()).enviar(anyString(), anyString());
        verify(acciones, never()).reemplazarInvitacion(any(), anyString(), anyString(), any(), any(), any());
    }

    @Test
    void proyeccionCombinaEnfriamientoYCuotaHoraria() {
        RepositorioAccionesOperador acciones = mock(RepositorioAccionesOperador.class);
        ServicioAdministracionInvitacionesOperador servicio = servicio(
                mock(RepositorioActivacionOperador.class), acciones, mock(ServicioActivacionOperador.class),
                mock(NotificadorInvitacionOperador.class), mock(ServicioEventosAdministracion.class), new ArrayList<>());
        when(acciones.consultarInvitacion(OPERADOR_ID)).thenReturn(Optional.of(invitacion(AHORA.minusSeconds(60))));
        when(acciones.contarAcciones(eq(OPERADOR_ID), anyString(), any(Instant.class))).thenAnswer(llamada -> {
            String operacion = llamada.getArgument(1);
            return switch (operacion) {
                case "REEMITIR_INVITACION" -> 2;
                case "REACTIVAR" -> 1;
                case "SOLICITAR_RECUPERACION" -> 3;
                default -> 0;
            };
        });
        when(acciones.ultimaAccion(OPERADOR_ID, "SOLICITAR_RECUPERACION"))
                .thenReturn(Optional.of(AHORA.minusSeconds(600)));
        when(acciones.primeraAccion(eq(OPERADOR_ID), any(), any(Instant.class)))
                .thenReturn(Optional.of(AHORA.minusSeconds(1800)));

        var proyeccion = servicio.consultar(OPERADOR_ID);

        assertEquals(0, proyeccion.reemisionesRestantes());
        assertEquals(0, proyeccion.recuperacionesRestantes());
        assertEquals(AHORA.plusSeconds(1800), proyeccion.reenvioDisponibleEn());
        assertEquals(AHORA.plusSeconds(1800), proyeccion.recuperacionDisponibleEn());
        assertFalse(proyeccion.puedeReemitirInvitacion());
        assertFalse(proyeccion.puedeSolicitarRecuperacion());
    }

    private static ServicioAdministracionInvitacionesOperador servicio(
            RepositorioActivacionOperador cuentas, RepositorioAccionesOperador acciones,
            ServicioActivacionOperador activacion, NotificadorInvitacionOperador notificador,
            ServicioEventosAdministracion eventos, List<String> orden) {
        when(activacion.origenValidado()).thenReturn(ORIGEN);
        doAnswer(llamada -> {
            orden.add("sse");
            return null;
        }).when(eventos).publicarDirectorioOperadorActualizado();
        return new ServicioAdministracionInvitacionesOperador(cuentas, acciones, activacion, notificador,
                eventos, transacciones(orden), Clock.fixed(AHORA, ZoneOffset.UTC), new java.security.SecureRandom());
    }

    private static PlatformTransactionManager transacciones(List<String> orden) {
        return new PlatformTransactionManager() {
            @Override
            public TransactionStatus getTransaction(TransactionDefinition definicion) {
                return new SimpleTransactionStatus();
            }

            @Override
            public void commit(TransactionStatus estado) {
                orden.add("commit");
            }

            @Override
            public void rollback(TransactionStatus estado) {
                orden.add("rollback");
            }
        };
    }

    private static void invitacionExistente(
            RepositorioActivacionOperador cuentas, RepositorioAccionesOperador acciones) {
        invitacionExistente(cuentas, acciones, AHORA.minusSeconds(61));
    }

    private static void invitacionExistente(
            RepositorioActivacionOperador cuentas, RepositorioAccionesOperador acciones, Instant generada) {
        when(cuentas.bloquearCuenta(OPERADOR_ID)).thenReturn(Optional.of(new CuentaActivacionOperador(
                OPERADOR_ID, RolCuenta.OPERADOR, "PENDIENTE", "operador@example.test", null, 4)));
        when(acciones.bloquearInvitacion(OPERADOR_ID)).thenReturn(Optional.of(invitacion(generada)));
        when(acciones.bloquearRecuperacion(OPERADOR_ID)).thenReturn(Optional.empty());
    }

    private static InvitacionOperadorPersistida invitacion(Instant generada) {
        return invitacion(generada, EstadoEnvioInvitacion.ENVIADO);
    }

    private static InvitacionOperadorPersistida invitacion(Instant generada, EstadoEnvioInvitacion estado) {
        return new InvitacionOperadorPersistida(OPERADOR_ID, "a".repeat(64), generada,
                generada.plusSeconds(7200), null, estado, generada);
    }
}
