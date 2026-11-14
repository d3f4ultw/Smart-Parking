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
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.correo.EstadoAviso;
import mx.smartparking.api.correo.NotificadorCorreo;
import mx.smartparking.api.persistencia.ConfiguracionPersistida;
import mx.smartparking.api.persistencia.RepositorioConfiguracion;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.transferencia.ProteccionIntentosTransferencia;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;

class ConfiguracionServicioPanelTest extends ConfiguracionServicioTestFixture {

    @Test
    void panelProyectaIdentidadDelPropietarioDesdeLaCuentaVinculada() {
        when(repositorio.obtener()).thenReturn(configuracionActiva());

        PanelPropietario panel = servicio.obtenerPanel(9);

        assertEquals("Ana", panel.propietario().nombres());
        assertEquals("López", panel.propietario().primerApellido());
        assertEquals("García", panel.propietario().segundoApellido());
        assertEquals("propietario@example.test", panel.propietario().correo());
    }

    @Test
    void renombrarConservaIdentidadYAvanzaRevisionSinInvalidarPropietario() {
        ConfiguracionPersistida actual = configuracionActiva();
        when(repositorio.bloquear()).thenReturn(actual);

        PanelPropietario resultado = servicio.renombrar("Centro Norte", 5, 9, CLAVE_IDEMPOTENCIA);

        assertEquals(6, resultado.revision());
        assertEquals(9, resultado.revisionPropietario());
        assertEquals(actual.estacionamientoId(), resultado.estacionamiento().id());
        assertEquals("Centro Norte", resultado.estacionamiento().nombre());
        verify(repositorio).renombrar(
                eq("Centro Norte"), eq(6L), any(UUID.class), eq(sha256(CLAVE_IDEMPOTENCIA)));
        verify(gestorSesiones, never()).revocarRevision(anyLong());
    }

    @Test
    void rechazaRevisionObsoletaSinModificarElNombre() {
        when(repositorio.bloquear()).thenReturn(configuracionActiva());

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.renombrar("Centro Norte", 4, 9, CLAVE_IDEMPOTENCIA));

        assertEquals(HttpStatus.PRECONDITION_FAILED, error.estadoHttp());
        verify(repositorio, never()).renombrar(anyString(), anyLong(), any(UUID.class), anyString());
    }

    @Test
    void repeticionIdempotenteDeRenombradoDevuelveElPanelSinEscribir() {
        ConfiguracionPersistida actual = configuracionActivaConClave(configuracionActiva(), CLAVE_IDEMPOTENCIA);
        when(repositorio.bloquear()).thenReturn(actual);

        PanelPropietario resultado = servicio.renombrar("Otro nombre", 4, 9, CLAVE_IDEMPOTENCIA);

        assertEquals(5, resultado.revision());
        assertEquals("Centro", resultado.estacionamiento().nombre());
        verify(repositorio, never()).renombrar(anyString(), anyLong(), any(UUID.class), anyString());
    }

    @Test
    void actualizarTipoYHorarioConservaIdentidadYAvanzaRevision() {
        ConfiguracionPersistida actual = configuracionActiva();
        HorarioConfiguracion horario = new HorarioConfiguracion(
                ModoHorario.INTERVALO_DIARIO,
                "America/Mexico_City",
                LocalTime.of(22, 0),
                LocalTime.of(6, 0));
        when(repositorio.bloquear()).thenReturn(actual);

        PanelPropietario resultado = servicio.actualizarDatosEstacionamiento(
                TipoEstacionamiento.MIXTO, horario, 5, 9, CLAVE_IDEMPOTENCIA);

        assertEquals(6, resultado.revision());
        assertEquals(9, resultado.revisionPropietario());
        assertEquals(actual.estacionamientoId(), resultado.estacionamiento().id());
        assertEquals(TipoEstacionamiento.MIXTO, resultado.estacionamiento().tipo());
        assertEquals("22:00", resultado.estacionamiento().horario().horaApertura());
        assertEquals("06:00", resultado.estacionamiento().horario().horaCierre());
        verify(repositorio).actualizarDatosEstacionamiento(
                eq(TipoEstacionamiento.MIXTO), eq(horario), eq(6L), any(UUID.class), eq(sha256(CLAVE_IDEMPOTENCIA)));
        verify(gestorSesiones, never()).revocarRevision(anyLong());
    }

    @Test
    void rechazaRevisionObsoletaAlActualizarTipoYHorario() {
        when(repositorio.bloquear()).thenReturn(configuracionActiva());
        HorarioConfiguracion horario = new HorarioConfiguracion(
                ModoHorario.INTERVALO_DIARIO,
                "America/Mexico_City",
                LocalTime.of(22, 0),
                LocalTime.of(6, 0));

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.actualizarDatosEstacionamiento(
                        TipoEstacionamiento.MIXTO, horario, 4, 9, CLAVE_IDEMPOTENCIA));

        assertEquals(HttpStatus.PRECONDITION_FAILED, error.estadoHttp());
        verify(repositorio, never()).actualizarDatosEstacionamiento(
                any(), any(), anyLong(), any(UUID.class), anyString());
    }

    @Test
    void repeticionIdempotenteDeEdicionDelHorarioNoAplicaDatosDistintos() {
        ConfiguracionPersistida actual = configuracionActivaConClave(configuracionActiva(), CLAVE_IDEMPOTENCIA);
        when(repositorio.bloquear()).thenReturn(actual);
        HorarioConfiguracion horario = new HorarioConfiguracion(
                ModoHorario.CONTINUO_24_7, "UTC", null, null);

        PanelPropietario resultado = servicio.actualizarDatosEstacionamiento(
                TipoEstacionamiento.MIXTO, horario, 4, 9, CLAVE_IDEMPOTENCIA);

        assertEquals(5, resultado.revision());
        assertEquals(TipoEstacionamiento.PUBLICO, resultado.estacionamiento().tipo());
        assertEquals(ModoHorario.INTERVALO_DIARIO, resultado.estacionamiento().horario().modo());
        verify(repositorio, never()).actualizarDatosEstacionamiento(
                any(), any(), anyLong(), any(UUID.class), anyString());
    }
}
