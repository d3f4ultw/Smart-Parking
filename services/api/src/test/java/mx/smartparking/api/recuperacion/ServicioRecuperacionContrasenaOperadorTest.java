package mx.smartparking.api.recuperacion;

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

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;
import mx.smartparking.api.activacion.ErrorLimitacionAccionOperador;
import mx.smartparking.api.activacion.ProteccionIntentosActivacion;
import mx.smartparking.api.activacion.SeguridadTokensOperador;
import mx.smartparking.api.activacion.ServicioActivacionOperador;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.correo.NotificadorRecuperacionOperador;
import mx.smartparking.api.persistencia.CuentaActivacionOperador;
import mx.smartparking.api.persistencia.RecuperacionContrasenaOperadorPersistida;
import mx.smartparking.api.persistencia.RepositorioAccionesOperador;
import mx.smartparking.api.persistencia.RepositorioActivacionOperador;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.Test;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;

class ServicioRecuperacionContrasenaOperadorTest {

    private static final Instant AHORA = Instant.parse("2026-10-25T18:00:00Z");
    private static final UUID OPERADOR_ID = UUID.fromString("3791848c-d816-46ba-8c56-34f9cf41e412");
    private static final String TOKEN = "A".repeat(43);
    private static final String TOKEN_HASH = SeguridadTokensOperador.hash(TOKEN);
    private static final String CLAVE = "idempotencia-recuperacion-01";

    @Test
    void correoFallidoSePersisteTrasCommitConVigenciaDeTreintaMinutos() {
        List<String> orden = new ArrayList<>();
        RepositorioActivacionOperador cuentas = mock(RepositorioActivacionOperador.class);
        RepositorioAccionesOperador acciones = mock(RepositorioAccionesOperador.class);
        NotificadorRecuperacionOperador notificador = mock(NotificadorRecuperacionOperador.class);
        ServicioActivacionOperador activacion = mock(ServicioActivacionOperador.class);
        GestorSesionesPropietario sesiones = mock(GestorSesionesPropietario.class);
        PasswordEncoder codificador = mock(PasswordEncoder.class);
        String[] enlaceEnviado = new String[1];
        ServicioRecuperacionContrasenaOperador servicio = servicio(
                cuentas, acciones, notificador, activacion, sesiones, codificador, orden,
                java.time.Clock.fixed(AHORA, java.time.ZoneOffset.UTC));
        when(cuentas.bloquearCuenta(OPERADOR_ID)).thenReturn(Optional.of(cuentaActiva()));
        when(acciones.bloquearInvitacion(OPERADOR_ID)).thenReturn(Optional.empty());
        when(acciones.bloquearRecuperacion(OPERADOR_ID)).thenReturn(Optional.empty());
        when(acciones.bloquearAccion(OPERADOR_ID, "SOLICITAR_RECUPERACION", SeguridadTokensOperador.hash(CLAVE)))
                .thenReturn(Optional.empty());
        when(acciones.ultimaAccion(OPERADOR_ID, "SOLICITAR_RECUPERACION")).thenReturn(Optional.empty());
        when(acciones.contarAcciones(eq(OPERADOR_ID), eq("SOLICITAR_RECUPERACION"), any(Instant.class)))
                .thenReturn(0);
        when(acciones.crearRecuperacion(eq(OPERADOR_ID), anyString(), eq(AHORA), eq(AHORA.plusSeconds(1800)), eq(AHORA)))
                .thenReturn(true);
        when(acciones.insertarAccion(eq(OPERADOR_ID), eq("SOLICITAR_RECUPERACION"), anyString(), eq(AHORA),
                eq(EstadoEnvioInvitacion.ENVIANDO), eq(9L), eq(AHORA.plusSeconds(1800)))).thenReturn(true);
        when(notificador.estaHabilitado()).thenReturn(true);
        when(notificador.enviarRecuperacion(eq("operador@example.test"), anyString())).thenAnswer(llamada -> {
            assertTrue(orden.contains("commit"));
            orden.add("smtp");
            enlaceEnviado[0] = llamada.getArgument(1);
            assertTrue(enlaceEnviado[0].startsWith("https://parking.example.test/restablecer-contrasena#"));
            return EstadoEnvioInvitacion.FALLIDO;
        });
        when(acciones.actualizarEstadoRecuperacion(eq(OPERADOR_ID), anyString(), eq(EstadoEnvioInvitacion.FALLIDO)))
                .thenReturn(true);

        ResultadoSolicitudRecuperacionOperador resultado = servicio.solicitar(OPERADOR_ID, "\"9\"", CLAVE);

        assertEquals(EstadoEnvioInvitacion.FALLIDO, resultado.respuesta().estadoEnvio());
        assertEquals(AHORA.plusSeconds(1800), resultado.respuesta().venceEn());
        assertEquals(AHORA.plusSeconds(900), resultado.respuesta().recuperacionDisponibleEn());
        String bearer = enlaceEnviado[0].substring(enlaceEnviado[0].indexOf('#') + 1);
        assertFalse(resultado.toString().contains(bearer));
        assertEquals(List.of("commit", "smtp", "commit"), orden);
        verify(acciones).actualizarEstadoAccion(
                OPERADOR_ID, "SOLICITAR_RECUPERACION", SeguridadTokensOperador.hash(CLAVE),
                EstadoEnvioInvitacion.FALLIDO);
        verify(sesiones, never()).revocarCuenta(OPERADOR_ID);
    }

    @Test
    void consumeUnaVezYRevocaSesionesSoloDespuesDelCommit() {
        List<String> orden = new ArrayList<>();
        RepositorioActivacionOperador cuentas = mock(RepositorioActivacionOperador.class);
        RepositorioAccionesOperador acciones = mock(RepositorioAccionesOperador.class);
        ServicioActivacionOperador activacion = mock(ServicioActivacionOperador.class);
        NotificadorRecuperacionOperador notificador = mock(NotificadorRecuperacionOperador.class);
        GestorSesionesPropietario sesiones = mock(GestorSesionesPropietario.class);
        PasswordEncoder codificador = mock(PasswordEncoder.class);
        ServicioRecuperacionContrasenaOperador servicio = servicio(
                cuentas, acciones, notificador, activacion, sesiones, codificador, orden,
                java.time.Clock.fixed(AHORA, java.time.ZoneOffset.UTC));
        RecuperacionContrasenaOperadorPersistida vigente = recuperacion(AHORA.plusSeconds(1800), null);
        when(acciones.buscarRecuperacionPorHash(TOKEN_HASH)).thenReturn(Optional.of(vigente), Optional.empty());
        when(cuentas.bloquearCuenta(OPERADOR_ID)).thenAnswer(llamada -> {
            orden.add("cuenta");
            return Optional.of(cuentaActiva());
        });
        when(acciones.bloquearInvitacion(OPERADOR_ID)).thenAnswer(llamada -> {
            orden.add("invitacion");
            return Optional.empty();
        });
        when(acciones.bloquearRecuperacion(OPERADOR_ID)).thenAnswer(llamada -> {
            orden.add("recuperacion");
            return Optional.of(vigente);
        });
        doAnswer(llamada -> {
            orden.add("acciones");
            return null;
        }).when(acciones).bloquearAcciones(OPERADOR_ID);
        when(codificador.encode("Nueva contraseña segura 2026!")).thenReturn("hash-nueva-contrasena");
        when(acciones.actualizarContrasena(OPERADOR_ID, 9, "hash-nueva-contrasena", AHORA))
                .thenAnswer(llamada -> {
                    orden.add("contrasena");
                    return true;
                });
        when(acciones.consumirRecuperacion(OPERADOR_ID, TOKEN_HASH, AHORA)).thenAnswer(llamada -> {
            orden.add("consumir");
            return true;
        });
        doAnswer(llamada -> {
            orden.add("revocar");
            return null;
        }).when(sesiones).revocarCuenta(OPERADOR_ID);
        SolicitudCompletarRecuperacionOperador solicitud = new SolicitudCompletarRecuperacionOperador(
                TOKEN, "Nueva contraseña segura 2026!", "Nueva contraseña segura 2026!");

        servicio.completar(solicitud);
        ErrorConfiguracion consumido = assertThrows(ErrorConfiguracion.class, () -> servicio.completar(solicitud));

        assertEquals(410, consumido.estadoHttp().value());
        assertEquals(List.of("cuenta", "invitacion", "recuperacion", "acciones",
                "contrasena", "consumir", "commit", "revocar"), orden);
        verify(acciones).actualizarContrasena(OPERADOR_ID, 9, "hash-nueva-contrasena", AHORA);
        verify(acciones).consumirRecuperacion(OPERADOR_ID, TOKEN_HASH, AHORA);
        verify(sesiones).revocarCuenta(OPERADOR_ID);
    }

    @Test
    void validacionNoConsumeTokenYNoPermiteReiniciarElBloqueo() {
        RepositorioActivacionOperador cuentas = mock(RepositorioActivacionOperador.class);
        RepositorioAccionesOperador acciones = mock(RepositorioAccionesOperador.class);
        NotificadorRecuperacionOperador notificador = mock(NotificadorRecuperacionOperador.class);
        ServicioActivacionOperador activacion = mock(ServicioActivacionOperador.class);
        GestorSesionesPropietario sesiones = mock(GestorSesionesPropietario.class);
        PasswordEncoder codificador = mock(PasswordEncoder.class);
        ProteccionIntentosActivacion intentos = new ProteccionIntentosActivacion();
        ServicioRecuperacionContrasenaOperador servicio = new ServicioRecuperacionContrasenaOperador(
                cuentas, acciones, notificador, activacion, codificador, intentos, sesiones,
                transacciones(new ArrayList<>()), java.time.Clock.fixed(AHORA, java.time.ZoneOffset.UTC),
                new java.security.SecureRandom());
        when(acciones.buscarRecuperacionPorHash(TOKEN_HASH)).thenReturn(Optional.of(recuperacion(AHORA.plusSeconds(1800), null)));

        for (int intento = 0; intento < 4; intento++) {
            assertThrows(ErrorConfiguracion.class, () -> servicio.completar(
                    new SolicitudCompletarRecuperacionOperador(TOKEN, "clave correcta 2026", "otra clave")));
        }
        assertTrue(servicio.validar(TOKEN).valida());
        assertThrows(ErrorConfiguracion.class, () -> servicio.completar(
                new SolicitudCompletarRecuperacionOperador(TOKEN, "clave correcta 2026", "otra clave")));
        ErrorConfiguracion bloqueada = assertThrows(ErrorConfiguracion.class, () -> servicio.validar(TOKEN));
        assertEquals(429, bloqueada.estadoHttp().value());

        verify(acciones, never()).consumirRecuperacion(any(), anyString(), any(Instant.class));
    }

    @Test
    void vencimientoExactoDeTreintaMinutosYaEsInvalido() {
        RepositorioAccionesOperador acciones = mock(RepositorioAccionesOperador.class);
        ServicioRecuperacionContrasenaOperador servicio = servicio(
                mock(RepositorioActivacionOperador.class), acciones, mock(NotificadorRecuperacionOperador.class),
                mock(ServicioActivacionOperador.class), mock(GestorSesionesPropietario.class),
                mock(PasswordEncoder.class), new ArrayList<>(),
                java.time.Clock.fixed(AHORA.plusSeconds(1800), java.time.ZoneOffset.UTC));
        when(acciones.buscarRecuperacionPorHash(TOKEN_HASH)).thenReturn(Optional.of(recuperacion(AHORA.plusSeconds(1800), null)));

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () -> servicio.validar(TOKEN));

        assertEquals(410, error.estadoHttp().value());
        assertEquals("TOKEN_RECUPERACION_INVALIDO", error.codigo());
    }

    private static ServicioRecuperacionContrasenaOperador servicio(
            RepositorioActivacionOperador cuentas, RepositorioAccionesOperador acciones,
            NotificadorRecuperacionOperador notificador, ServicioActivacionOperador activacion,
            GestorSesionesPropietario sesiones, PasswordEncoder codificador, List<String> orden,
            java.time.Clock reloj) {
        when(activacion.origenValidado()).thenReturn("https://parking.example.test");
        return new ServicioRecuperacionContrasenaOperador(cuentas, acciones, notificador, activacion,
                codificador, new ProteccionIntentosActivacion(), sesiones,
                transacciones(orden), reloj, new java.security.SecureRandom());
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

    private static CuentaActivacionOperador cuentaActiva() {
        return new CuentaActivacionOperador(OPERADOR_ID, RolCuenta.OPERADOR, "ACTIVA",
                "operador@example.test", "hash-existente", 9);
    }

    private static RecuperacionContrasenaOperadorPersistida recuperacion(Instant venceEn, Instant consumidaEn) {
        return new RecuperacionContrasenaOperadorPersistida(OPERADOR_ID, TOKEN_HASH, AHORA.minusSeconds(1),
                venceEn, consumidaEn, EstadoEnvioInvitacion.ENVIADO, AHORA.minusSeconds(1));
    }

}
