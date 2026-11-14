package mx.smartparking.api.configuracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
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
import org.junit.jupiter.api.Test;

class ConfiguracionServicioTest extends ConfiguracionServicioTestFixture {

    @Test
    void registraYNotificaLaBienvenidaSoloDespuesDelCommit() {
        when(repositorio.bloquear()).thenAnswer(invocacion -> {
            eventosTransaccion.add("bloquear");
            return configuracionSinConfigurar();
        });
        when(codificador.encode("Acceso seguro 2026")).thenReturn("hash-acceso-nuevo");
        when(codificador.encode("Administracion segura 2026")).thenReturn("hash-admin-nuevo");
        doAnswer(invocacion -> {
            eventosTransaccion.add("configurar");
            return null;
        }).when(repositorio).configurarInicial(
                any(), anyString(), any(UUID.class), any(UUID.class), anyLong(), anyLong(), any(UUID.class), anyString());
        when(notificador.enviarBienvenida(anyString(), anyString(), anyString())).thenAnswer(invocacion -> {
            eventosTransaccion.add("bienvenida");
            return EstadoAviso.ENVIADO;
        });
        doAnswer(invocacion -> {
            eventosTransaccion.add("guardar-aviso");
            return null;
        }).when(repositorio).actualizarEstadoAviso(
                any(UUID.class), eq(RepositorioConfiguracion.TipoAviso.BIENVENIDA), eq("ENVIADO"));

        ResultadoConfiguracion resultado = servicio.configurarInicial(solicitudValida(), CLAVE_IDEMPOTENCIA);

        assertEquals(EstadoConfiguracion.CONFIGURADA, resultado.estado());
        assertEquals(1, resultado.revision());
        assertEquals(EstadoAviso.ENVIADO, resultado.avisoBienvenida());
        assertEquals(List.of("inicio", "bloquear", "configurar", "commit", "bienvenida", "guardar-aviso"),
                eventosTransaccion);
        verify(repositorio).configurarInicial(
                any(),
                eq("hash-admin-nuevo"),
                any(UUID.class),
                any(UUID.class),
                eq(1L),
                eq(1L),
                any(UUID.class),
                eq(sha256(CLAVE_IDEMPOTENCIA)));
    }

    @Test
    void fallaElRegistroConRollbackYNoEnviaLaBienvenida() {
        when(repositorio.bloquear()).thenAnswer(invocacion -> {
            eventosTransaccion.add("bloquear");
            return configuracionSinConfigurar();
        });
        when(codificador.encode("Acceso seguro 2026")).thenReturn("hash-acceso-nuevo");
        when(codificador.encode("Administracion segura 2026")).thenReturn("hash-admin-nuevo");
        doAnswer(invocacion -> {
            eventosTransaccion.add("configurar");
            throw new IllegalStateException("fallo simulado de persistencia");
        }).when(repositorio).configurarInicial(
                any(), anyString(), any(UUID.class), any(UUID.class), anyLong(), anyLong(), any(UUID.class), anyString());

        assertThrows(IllegalStateException.class,
                () -> servicio.configurarInicial(solicitudValida(), CLAVE_IDEMPOTENCIA));

        assertEquals(List.of("inicio", "bloquear", "configurar", "rollback"), eventosTransaccion);
        verify(notificador, never()).enviarBienvenida(anyString(), anyString(), anyString());
        verify(repositorio, never()).actualizarEstadoAviso(any(UUID.class), any(), anyString());
    }

    @Test
    void replayDeConfiguracionDevuelveResultadoSinReenviarBienvenida() {
        ConfiguracionPersistida activa = configuracionActiva();
        ConfiguracionPersistida mismaOperacion = new ConfiguracionPersistida(
                activa.estado(), activa.revision(), activa.revisionPropietario(), activa.estacionamientoId(),
                activa.propietarioNombres(), activa.propietarioPrimerApellido(), activa.propietarioSegundoApellido(),
                activa.correoPropietario(), activa.hashContrasenaAcceso(), activa.hashContrasenaAdministrativa(),
                activa.nombreEstacionamiento(), activa.tipoEstacionamiento(), activa.modoHorario(), activa.zonaHoraria(),
                activa.horaApertura(), activa.horaCierre(), activa.transferId(), activa.hashGrantTransferencia(),
                activa.grantVenceEn(), activa.hashRecuperacionTransferencia(), activa.estadoAvisoTransferencia(),
                "ENVIADO", activa.ultimaOperacionId(), sha256(CLAVE_IDEMPOTENCIA));
        when(repositorio.bloquear()).thenReturn(mismaOperacion);

        ResultadoConfiguracion resultado = servicio.configurarInicial(solicitudValida(), CLAVE_IDEMPOTENCIA);

        assertEquals(EstadoConfiguracion.CONFIGURADA, resultado.estado());
        assertEquals(5, resultado.revision());
        assertEquals(EstadoAviso.ENVIADO, resultado.avisoBienvenida());
        verify(repositorio, never()).configurarInicial(any(), anyString(), any(), any(), anyLong(), anyLong(), any(), anyString());
        verify(notificador, never()).enviarBienvenida(anyString(), anyString(), anyString());
    }
}
