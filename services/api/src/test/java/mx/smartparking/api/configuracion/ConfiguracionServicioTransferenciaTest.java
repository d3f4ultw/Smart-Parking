package mx.smartparking.api.configuracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.correo.EstadoAviso;
import mx.smartparking.api.persistencia.ConfiguracionPersistida;
import mx.smartparking.api.persistencia.RepositorioConfiguracion;
import mx.smartparking.api.transferencia.ProteccionIntentosTransferencia;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

class ConfiguracionServicioTransferenciaTest extends ConfiguracionServicioTestFixture {

    @Test
    void desvinculaEnLaTransaccionRevocaSesionYNotificaTrasCommit() {
        when(repositorio.bloquear()).thenReturn(configuracionActivaSinPerfilLegado());
        UUID cuentaId = UUID.randomUUID();
        when(cuentas.duenoActual()).thenReturn(java.util.Optional.of(
                new mx.smartparking.api.persistencia.CuentaPersistida(
                        cuentaId, "Ana", "López", "García", "propietario@example.test",
                        "propietario@example.test", mx.smartparking.api.seguridad.RolCuenta.DUENO,
                        true, "hash-acceso", 1)));
        when(codificador.matches(CONTRASENA_ADMINISTRATIVA, "hash-admin-activo")).thenReturn(true);
        when(notificador.notificarDesvinculacion("propietario@example.test", "Ana López García", "Centro"))
                .thenReturn(EstadoAviso.ENVIADO);

        ResultadoTransferencia resultado = servicio.iniciarTransferencia(
                CONTRASENA_ADMINISTRATIVA,
                5,
                9,
                CLAVE_IDEMPOTENCIA,
                "127.0.0.1");

        assertEquals(EstadoConfiguracion.TRANSFERENCIA_PENDIENTE, resultado.estado());
        assertNotNull(resultado.transferenciaId());
        assertNotNull(resultado.grant());
        assertEquals(AHORA.plusSeconds(30 * 60), resultado.venceEn());
        assertEquals(EstadoAviso.ENVIADO, resultado.avisoTransferencia());
        verify(repositorio).iniciarTransferencia(
                eq(resultado.transferenciaId()),
                eq(sha256(resultado.grant())),
                eq(AHORA.plusSeconds(30 * 60)),
                eq("hash-admin-activo"),
                eq(6L),
                eq(10L),
                any(UUID.class),
                anyString());
        eventosTransaccion.add("desactivar-cuenta-verificado");
        verify(cuentas).desactivar(cuentaId);
        verify(gestorSesiones).revocarRevision(9);
        verify(proteccionIntentos).registrarExito(ProteccionIntentosTransferencia.Operacion.INICIO, "127.0.0.1");
        verify(notificador).notificarDesvinculacion("propietario@example.test", "Ana López García", "Centro");
    }

    @Test
    void contrasenaAdministrativaIncorrectaNoCambiaEstadoNiNotifica() {
        when(repositorio.bloquear()).thenReturn(configuracionActiva());
        when(codificador.matches(CONTRASENA_ADMINISTRATIVA, "hash-admin-activo")).thenReturn(false);

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.iniciarTransferencia(CONTRASENA_ADMINISTRATIVA, 5, 9, CLAVE_IDEMPOTENCIA, "127.0.0.1"));

        assertEquals(HttpStatus.FORBIDDEN, error.estadoHttp());
        verify(repositorio, never()).iniciarTransferencia(any(), anyString(), any(), anyString(), anyLong(), anyLong(), any(), anyString());
        verify(gestorSesiones, never()).revocarRevision(anyLong());
        verify(notificador, never()).notificarDesvinculacion(anyString(), anyString(), anyString());
        verify(proteccionIntentos).registrarFallo(ProteccionIntentosTransferencia.Operacion.INICIO, "127.0.0.1");
    }

    @Test
    void limiteStepUpRechazaAntesDeLeerOCambiarLaConfiguracion() {
        when(proteccionIntentos.permitido(ProteccionIntentosTransferencia.Operacion.INICIO, "127.0.0.1"))
                .thenReturn(false);

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.iniciarTransferencia(CONTRASENA_ADMINISTRATIVA, 5, 9, CLAVE_IDEMPOTENCIA, "127.0.0.1"));

        assertEquals(HttpStatus.FORBIDDEN, error.estadoHttp());
        verify(repositorio, never()).bloquear();
        verify(codificador, never()).matches(anyString(), anyString());
        verify(notificador, never()).notificarDesvinculacion(anyString(), anyString(), anyString());
    }

    @Test
    void recuperarSoloReemiteGrantYNoEnviaCorreo() {
        UUID transferId = UUID.randomUUID();
        when(repositorio.bloquear()).thenReturn(configuracionPendiente(transferId));
        when(codificador.matches(CONTRASENA_ADMINISTRATIVA, "hash-admin-recuperacion")).thenReturn(true);

        ResultadoTransferencia resultado = servicio.recuperarTransferencia(CONTRASENA_ADMINISTRATIVA, "127.0.0.1");

        assertEquals(EstadoConfiguracion.TRANSFERENCIA_PENDIENTE, resultado.estado());
        assertEquals(transferId, resultado.transferenciaId());
        assertNotNull(resultado.grant());
        assertEquals(AHORA.plusSeconds(30 * 60), resultado.venceEn());
        assertNotEquals("previous-grant", resultado.grant());
        assertNotEquals(sha256("previous-grant"), sha256(resultado.grant()));
        verify(repositorio).reemitirGrant(eq(sha256(resultado.grant())), eq(resultado.venceEn()), eq(13L));
        verify(notificador, never()).enviarBienvenida(anyString(), anyString(), anyString());
        verify(notificador, never()).notificarDesvinculacion(anyString(), anyString(), anyString());
        verify(proteccionIntentos).registrarExito(ProteccionIntentosTransferencia.Operacion.RECUPERACION, "127.0.0.1");
        assertFalse(resultado.toString().contains(resultado.grant()));
    }

    @Test
    void completarTransferenciaAceptaGrantVigenteYConservaOrdenPostCommit() {
        UUID transferId = UUID.randomUUID();
        String grant = "grant-valido-para-prueba";
        ConfiguracionPersistida pendiente = configuracionPendiente(
                transferId, sha256(grant), AHORA.plusSeconds(60));
        when(repositorio.bloquear()).thenAnswer(invocacion -> {
            eventosTransaccion.add("bloquear");
            return pendiente;
        });
        when(codificador.encode("Acceso seguro 2026")).thenReturn("hash-acceso-nuevo");
        when(codificador.encode("Administracion segura 2026")).thenReturn("hash-admin-nuevo");
        doAnswer(invocacion -> {
            eventosTransaccion.add("completar");
            return null;
        }).when(repositorio).completarTransferencia(
                any(), anyString(), any(UUID.class), anyLong(), anyLong(), any(UUID.class), anyString());
        when(notificador.enviarBienvenida(anyString(), anyString(), anyString())).thenAnswer(invocacion -> {
            eventosTransaccion.add("bienvenida");
            return EstadoAviso.ENVIADO;
        });
        doAnswer(invocacion -> {
            eventosTransaccion.add("guardar-aviso");
            return null;
        }).when(repositorio).actualizarEstadoAviso(
                any(UUID.class), eq(RepositorioConfiguracion.TipoAviso.BIENVENIDA), eq("ENVIADO"));

        ResultadoConfiguracion resultado = servicio.completarTransferencia(
                grant, solicitudValida(), CLAVE_IDEMPOTENCIA, "127.0.0.1");

        assertEquals(EstadoConfiguracion.CONFIGURADA, resultado.estado());
        assertEquals(13, resultado.revision());
        assertEquals(EstadoAviso.ENVIADO, resultado.avisoBienvenida());
        assertEquals(List.of("inicio", "bloquear", "completar", "commit", "bienvenida", "guardar-aviso"),
                eventosTransaccion);
        verify(repositorio).completarTransferencia(
                any(),
                eq("hash-admin-nuevo"),
                any(UUID.class),
                eq(13L),
                eq(11L),
                any(UUID.class), eq(sha256(CLAVE_IDEMPOTENCIA)));
    }

    @Test
    void rechazaGrantVencidoSinCompletarNiEnviarCorreo() {
        UUID transferId = UUID.randomUUID();
        String grant = "grant-vencido-para-prueba";
        when(repositorio.bloquear()).thenReturn(configuracionPendiente(
                transferId, sha256(grant), AHORA));
        when(codificador.encode("Acceso seguro 2026")).thenReturn("hash-acceso-nuevo");
        when(codificador.encode("Administracion segura 2026")).thenReturn("hash-admin-nuevo");

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.completarTransferencia(grant, solicitudValida(), CLAVE_IDEMPOTENCIA, "127.0.0.1"));

        assertEquals(HttpStatus.FORBIDDEN, error.estadoHttp());
        verify(repositorio, never()).completarTransferencia(any(), anyString(), any(UUID.class), anyLong(), anyLong(), any(), anyString());
        verify(notificador, never()).enviarBienvenida(anyString(), anyString(), anyString());
        verify(proteccionIntentos).registrarFallo(ProteccionIntentosTransferencia.Operacion.GRANT, "127.0.0.1");
    }

    @Test
    void repeticionDeFinalizacionNoReenviaBienvenida() {
        ConfiguracionPersistida actual = configuracionActivaConClave(configuracionActiva(), CLAVE_IDEMPOTENCIA);
        when(repositorio.bloquear()).thenReturn(actual);
        when(codificador.encode("Acceso seguro 2026")).thenReturn("hash-acceso-nuevo");
        when(codificador.encode("Administracion segura 2026")).thenReturn("hash-admin-nuevo");

        ResultadoConfiguracion resultado = servicio.completarTransferencia(
                "grant-anterior", solicitudValida(), CLAVE_IDEMPOTENCIA, "127.0.0.1");

        assertEquals(5, resultado.revision());
        assertEquals(EstadoAviso.ENVIADO, resultado.avisoBienvenida());
        verify(repositorio, never()).completarTransferencia(any(), anyString(), any(UUID.class), anyLong(), anyLong(), any(), anyString());
        verify(notificador, never()).enviarBienvenida(anyString(), anyString(), anyString());
    }
}
