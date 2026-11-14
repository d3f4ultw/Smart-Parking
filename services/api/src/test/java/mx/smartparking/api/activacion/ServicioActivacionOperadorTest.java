package mx.smartparking.api.activacion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.empleados.coordinacion.EmpleadoEnlaceOperador;
import mx.smartparking.api.persistencia.RepositorioActivacionOperador.ResultadoActualizacionEnvio;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;
import org.springframework.http.HttpStatus;

class ServicioActivacionOperadorTest extends ServicioActivacionOperadorTestSupport {

    @Test
    void preparaUnaInvitacionHashOnlyYRedactaElSobre() {
        PreparacionInvitacionOperador preparacion = servicio.prepararInicial(OPERADOR_ID, "operador@example.test");

        verify(repositorio).crearInicial(eq(OPERADOR_ID), anyString(), eq(AHORA), eq(AHORA.plusSeconds(7200)));
        assertFalse(preparacion.toString().contains("operador@example.test"));
        assertTrue(preparacion.toString().contains("REDACTADOS"));
    }

    @Test
    void validarNoConsumeElToken() {
        when(repositorio.buscarPorTokenHash(TOKEN_HASH)).thenReturn(Optional.of(invitacion(TOKEN_HASH,
                AHORA.plusSeconds(7200), null, EstadoEnvioInvitacion.ENVIANDO)));

        assertTrue(servicio.validar(TOKEN).valida());

        verify(repositorio, never()).consumir(any(UUID.class), anyString(), any(Instant.class));
        verify(repositorio, never()).activar(any(UUID.class), org.mockito.ArgumentMatchers.anyLong(),
                anyString(), any(Instant.class));
        verify(publicadorEventos, never()).publicarDirectorioOperadorActualizado();
    }

    @Test
    void validarNoReiniciaElBloqueoDeCincoFallosDeContrasena() {
        when(repositorio.buscarPorTokenHash(TOKEN_HASH)).thenReturn(Optional.of(invitacion(TOKEN_HASH,
                AHORA.plusSeconds(7200), null, EstadoEnvioInvitacion.ENVIADO)));
        SolicitudCompletarActivacionOperador contrasenaIncorrecta = new SolicitudCompletarActivacionOperador(
                TOKEN, "contrasena segura 2026", "otra contrasena segura 2026");

        for (int intento = 0; intento < 4; intento++) {
            assertThrows(ErrorConfiguracion.class, () -> servicio.completar(contrasenaIncorrecta));
        }
        assertTrue(servicio.validar(TOKEN).valida());
        assertThrows(ErrorConfiguracion.class, () -> servicio.completar(contrasenaIncorrecta));

        ErrorConfiguracion bloqueada = assertThrows(ErrorConfiguracion.class, () -> servicio.validar(TOKEN));

        assertEquals(HttpStatus.TOO_MANY_REQUESTS, bloqueada.estadoHttp());
        verify(repositorio, never()).consumir(any(UUID.class), anyString(), any(Instant.class));
        verify(repositorio, never()).activar(any(UUID.class), org.mockito.ArgumentMatchers.anyLong(),
                anyString(), any(Instant.class));
    }

    @Test
    void limiteExactoDeDosHorasYaEsInvalido() {
        when(repositorio.buscarPorTokenHash(TOKEN_HASH)).thenReturn(Optional.of(invitacion(TOKEN_HASH,
                AHORA, null, EstadoEnvioInvitacion.ENVIADO)));

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () -> servicio.validar(TOKEN));

        assertEquals(HttpStatus.GONE, error.estadoHttp());
        assertEquals("INVITACION_NO_VALIDA", error.codigo());
    }

    @Test
    void completaCuentaYConsumeTokenEnOrdenAtomico() {
        SolicitudCompletarActivacionOperador solicitud = new SolicitudCompletarActivacionOperador(
                TOKEN, "contrasena segura 2026", "contrasena segura 2026");
        when(repositorio.buscarPorTokenHash(TOKEN_HASH)).thenReturn(Optional.of(invitacion(TOKEN_HASH,
                AHORA.plusSeconds(7200), null, EstadoEnvioInvitacion.ENVIADO)));
        when(repositorio.bloquearCuenta(OPERADOR_ID)).thenReturn(Optional.of(cuentaPendiente()));
        when(repositorio.bloquearInvitacion(OPERADOR_ID)).thenReturn(Optional.of(invitacion(TOKEN_HASH,
                AHORA.plusSeconds(7200), null, EstadoEnvioInvitacion.ENVIADO)));
        when(codificador.encode("contrasena segura 2026")).thenReturn("hash-password");
        when(repositorio.activar(OPERADOR_ID, 0, "hash-password", AHORA)).thenReturn(true);
        when(repositorio.consumir(OPERADOR_ID, TOKEN_HASH, AHORA)).thenReturn(true);

        servicio.completar(solicitud);

        InOrder orden = inOrder(repositorio);
        orden.verify(repositorio).buscarPorTokenHash(TOKEN_HASH);
        orden.verify(repositorio).bloquearCuenta(OPERADOR_ID);
        orden.verify(repositorio).bloquearInvitacion(OPERADOR_ID);
        orden.verify(repositorio).activar(OPERADOR_ID, 0, "hash-password", AHORA);
        orden.verify(repositorio).consumir(OPERADOR_ID, TOKEN_HASH, AHORA);
        verify(publicadorEventos).publicarDirectorioOperadorActualizado();
    }

    @Test
    void activacionVinculadaBloqueaEmpleadoAntesDeCuentaEIncrementaRevision() {
        long empleadoId = 42;
        EmpleadoEnlaceOperador empleado = new EmpleadoEnlaceOperador(
                empleadoId, "E-0042", "ACTIVO", 9, "operador@example.test", "operador@example.test");
        SolicitudCompletarActivacionOperador solicitud = new SolicitudCompletarActivacionOperador(
                TOKEN, "contrasena segura 2026", "contrasena segura 2026");
        when(repositorio.buscarPorTokenHash(TOKEN_HASH)).thenReturn(Optional.of(invitacion(TOKEN_HASH,
                AHORA.plusSeconds(7200), null, EstadoEnvioInvitacion.ENVIADO)));
        when(repositorio.empleadoId(OPERADOR_ID)).thenReturn(Optional.of(empleadoId));
        when(empleados.bloquearPorId(empleadoId)).thenReturn(Optional.of(empleado));
        when(repositorio.bloquearCuenta(OPERADOR_ID)).thenReturn(Optional.of(cuentaPendiente(empleadoId)));
        when(repositorio.bloquearInvitacion(OPERADOR_ID)).thenReturn(Optional.of(invitacion(TOKEN_HASH,
                AHORA.plusSeconds(7200), null, EstadoEnvioInvitacion.ENVIADO)));
        when(codificador.encode("contrasena segura 2026")).thenReturn("hash-password");
        when(repositorio.activar(OPERADOR_ID, 0, "hash-password", AHORA)).thenReturn(true);
        when(repositorio.consumir(OPERADOR_ID, TOKEN_HASH, AHORA)).thenReturn(true);
        when(empleados.incrementarRevision(empleadoId, 9)).thenReturn(true);

        servicio.completar(solicitud);

        InOrder orden = inOrder(repositorio, empleados);
        orden.verify(repositorio).buscarPorTokenHash(TOKEN_HASH);
        orden.verify(repositorio).empleadoId(OPERADOR_ID);
        orden.verify(empleados).bloquearPorId(empleadoId);
        orden.verify(repositorio).bloquearCuenta(OPERADOR_ID);
        orden.verify(repositorio).bloquearInvitacion(OPERADOR_ID);
        orden.verify(repositorio).activar(OPERADOR_ID, 0, "hash-password", AHORA);
        orden.verify(repositorio).consumir(OPERADOR_ID, TOKEN_HASH, AHORA);
        orden.verify(empleados).incrementarRevision(empleadoId, 9);
        verify(publicadorEventos).publicarDirectorioOperadorActualizado();
        verify(publicadorEventos).publicarDirectorioActualizado();
    }

    @Test
    void contrasenaInvalidaNoConsumeLaInvitacion() {
        when(repositorio.buscarPorTokenHash(TOKEN_HASH)).thenReturn(Optional.of(invitacion(TOKEN_HASH,
                AHORA.plusSeconds(7200), null, EstadoEnvioInvitacion.ENVIADO)));
        SolicitudCompletarActivacionOperador solicitud = new SolicitudCompletarActivacionOperador(
                TOKEN, "corta", "distinta");

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () -> servicio.completar(solicitud));

        assertEquals(HttpStatus.BAD_REQUEST, error.estadoHttp());
        verify(repositorio, never()).activar(any(UUID.class), org.mockito.ArgumentMatchers.anyLong(),
                anyString(), any(Instant.class));
        verify(repositorio, never()).consumir(any(UUID.class), anyString(), any(Instant.class));
        verify(publicadorEventos, never()).publicarDirectorioOperadorActualizado();
    }

    @Test
    void noPublicaCuandoElResultadoSmtpNoCambiaLaProyeccionDeInvitacionExpirada() {
        PreparacionInvitacionOperador preparacion = new PreparacionInvitacionOperador(
                OPERADOR_ID, "operador@example.test", TOKEN, TOKEN_HASH, AHORA.minusSeconds(1), ORIGEN);
        when(notificador.enviar(anyString(), anyString())).thenReturn(EstadoEnvioInvitacion.FALLIDO);
        when(repositorio.actualizarResultadoEnvio(
                OPERADOR_ID, TOKEN_HASH, EstadoEnvioInvitacion.FALLIDO))
                .thenReturn(Optional.of(new ResultadoActualizacionEnvio(EstadoEnvioInvitacion.FALLIDO, true, false)));

        EstadoEnvioInvitacion resultado = servicio.enviarInicial(preparacion);

        assertEquals(EstadoEnvioInvitacion.FALLIDO, resultado);
        verify(publicadorEventos, never()).publicarDirectorioOperadorActualizado();
    }
}
