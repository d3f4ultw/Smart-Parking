package mx.smartparking.api.rfid1.persistencia;

import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.CapturaRfid1Persistida;
import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.DestinoRfid1Persistido;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.configuracion.TipoEstacionamiento;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class RepositorioConfirmacionRfid1JdbcTest {

    private static final Instant AHORA = Instant.parse("2026-10-27T20:00:00Z");
    private static final String CAPTURA_ID = "0a2c3e4f6a8b4c0d9e1f2a3b4c5d6e7f";
    private static final UUID PROPIETARIO_ID = UUID.fromString("13f989d5-117d-47ce-8845-2cead6cfba44");
    private static final UUID CLIENTE_ID = UUID.fromString("9f0108fd-8a8d-4051-89d0-4bb6ef09d8a7");
    private static final String HUELLA_SESION = "c".repeat(64);
    private static final String HUELLA_UID = "a".repeat(64);
    private static final String CLAVE_HASH = "f".repeat(64);

    @Test
    void confirmarBloqueaCapturaLuegoContextoYDestinoAntesDeInsertar() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        ResolutorDestinoRfid1 resolutor = mock(ResolutorDestinoRfid1.class);
        RepositorioConfirmacionRfid1Jdbc repositorio = new RepositorioConfirmacionRfid1Jdbc(jdbc, resolutor);
        prepararConfirmacion(jdbc, resolutor, captura("VISTA_PREVIA", null, null, null));
        when(jdbc.queryForObject(anyString(), org.mockito.ArgumentMatchers.eq(Boolean.class), any()))
                .thenReturn(false, false);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class)))
                .thenReturn(List.of(captura("VISTA_PREVIA", null, null, null)),
                        List.of(PROPIETARIO_ID),
                        List.of(vistaTemporal()),
                        List.of(43L));
        when(jdbc.query(anyString(), any(RowMapper.class)))
                .thenReturn(List.of(TipoEstacionamiento.PRIVADO));
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);

        var resultado = repositorio.confirmarCaptura(
                CAPTURA_ID, PROPIETARIO_ID, 2, 4, HUELLA_SESION, CLAVE_HASH, AHORA);

        assertEquals("COMPLETADA", resultado.estado());
        assertEquals(43L, resultado.asociacionId());
        assertNull(resultado.codigoError());
        assertFalse(resultado.repetida());
        ArgumentCaptor<String> consultas = ArgumentCaptor.forClass(String.class);
        verify(jdbc, times(4)).query(consultas.capture(), any(RowMapper.class), any(Object[].class));
        assertTrue(consultas.getAllValues().get(0).contains("FOR UPDATE"));
        assertTrue(consultas.getAllValues().get(1).contains("FOR UPDATE OF cuenta, configuracion"));
        assertTrue(consultas.getAllValues().get(2).contains("uid_temporal_rfid1"));
        assertTrue(consultas.getAllValues().get(3).contains("ON CONFLICT DO NOTHING"));
        ArgumentCaptor<String> consultaModalidad = ArgumentCaptor.forClass(String.class);
        verify(jdbc).query(consultaModalidad.capture(), any(RowMapper.class));
        assertTrue(consultaModalidad.getValue().contains("tipo_estacionamiento"));
        assertTrue(consultaModalidad.getValue().contains("FOR SHARE"));
        verify(jdbc, never()).update(org.mockito.ArgumentMatchers.contains("DELETE FROM uid_temporal_rfid1"),
                any(Object[].class));
    }

    @Test
    void mismoHashDespuesDePerderRespuestaReproduceAsociacion() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioConfirmacionRfid1Jdbc repositorio = new RepositorioConfirmacionRfid1Jdbc(
                jdbc, mock(ResolutorDestinoRfid1.class));
        CapturaRfid1Persistida completada = captura("COMPLETADA", CLAVE_HASH, null, 43L);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class)))
                .thenReturn(List.of(completada), List.of(PROPIETARIO_ID));

        var resultado = repositorio.confirmarCaptura(
                CAPTURA_ID, PROPIETARIO_ID, 2, 4, HUELLA_SESION, CLAVE_HASH, AHORA);

        assertEquals("COMPLETADA", resultado.estado());
        assertEquals(43L, resultado.asociacionId());
        assertTrue(resultado.repetida());
    }

    @Test
    void otraSesionNoPuedeLeerVistaPreviaNiConfirmar() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioConfirmacionRfid1Jdbc repositorio = new RepositorioConfirmacionRfid1Jdbc(
                jdbc, mock(ResolutorDestinoRfid1.class));
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class)))
                .thenReturn(List.of(captura("VISTA_PREVIA", null, null, null)));

        Optional<RepositorioRfid1.VistaPreviaRfid1Persistida> vista = repositorio.consultarVistaPrevia(
                CAPTURA_ID, PROPIETARIO_ID, 2, 4, "d".repeat(64), AHORA);
        var resultado = repositorio.confirmarCaptura(
                CAPTURA_ID, PROPIETARIO_ID, 2, 4, "d".repeat(64), CLAVE_HASH, AHORA);

        assertTrue(vista.isEmpty());
        assertEquals("CAPTURA_NO_ENCONTRADA", resultado.codigoError());
        verify(jdbc, never()).update(anyString(), any(Object[].class));
    }

    @Test
    void modalidadCambiadaAntesDeConfirmarCancelaLaCapturaSinAsociar() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        ResolutorDestinoRfid1 resolutor = mock(ResolutorDestinoRfid1.class);
        RepositorioConfirmacionRfid1Jdbc repositorio = new RepositorioConfirmacionRfid1Jdbc(jdbc, resolutor);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class)))
                .thenReturn(List.of(captura("VISTA_PREVIA", null, null, null)),
                        List.of(PROPIETARIO_ID),
                        List.of(vistaTemporal()));
        when(jdbc.query(anyString(), any(RowMapper.class)))
                .thenReturn(List.of(TipoEstacionamiento.PUBLICO));
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);

        var resultado = repositorio.confirmarCaptura(
                CAPTURA_ID, PROPIETARIO_ID, 2, 4, HUELLA_SESION, CLAVE_HASH, AHORA);

        assertEquals("CAPTURA_NO_VIGENTE", resultado.codigoError());
        assertEquals("CANCELADA", resultado.estado());
        verify(resolutor, never()).resolver("EMPLEADO", "E-0007");
        verify(jdbc, never()).queryForObject(anyString(), org.mockito.ArgumentMatchers.eq(Boolean.class), any());
        verify(jdbc).update(org.mockito.ArgumentMatchers.contains("SET estado = ?"), any(Object[].class));
    }

    @Test
    void confirmacionRevalidaEstadoActivoAntesDeAsociar() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        ResolutorDestinoRfid1 resolutor = mock(ResolutorDestinoRfid1.class);
        RepositorioConfirmacionRfid1Jdbc repositorio = new RepositorioConfirmacionRfid1Jdbc(jdbc, resolutor);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class)))
                .thenReturn(List.of(captura("VISTA_PREVIA", null, null, null)),
                        List.of(PROPIETARIO_ID),
                        List.of(vistaTemporal()));
        when(jdbc.query(anyString(), any(RowMapper.class)))
                .thenReturn(List.of(TipoEstacionamiento.PRIVADO));
        when(resolutor.resolver("EMPLEADO", "E-0007"))
                .thenReturn(Optional.of(new DestinoRfid1Persistido("EMPLEADO", "E-0007", null, 7L, false)));
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);

        var resultado = repositorio.confirmarCaptura(
                CAPTURA_ID, PROPIETARIO_ID, 2, 4, HUELLA_SESION, CLAVE_HASH, AHORA);

        assertEquals("CAPTURA_NO_VIGENTE", resultado.codigoError());
        assertEquals("CANCELADA", resultado.estado());
        verify(jdbc, never()).queryForObject(anyString(), org.mockito.ArgumentMatchers.eq(Boolean.class), any());
        verify(jdbc, never()).query(org.mockito.ArgumentMatchers.contains("INSERT INTO asociacion_tarjeta_rfid1"),
                any(RowMapper.class), any(Object[].class));
    }

    @Test
    void confirmacionRevalidaMembresiaAntesDeAsociar() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        ResolutorDestinoRfid1 resolutor = mock(ResolutorDestinoRfid1.class);
        RepositorioConfirmacionRfid1Jdbc repositorio = new RepositorioConfirmacionRfid1Jdbc(jdbc, resolutor);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class)))
                .thenReturn(List.of(capturaCliente("VISTA_PREVIA")),
                        List.of(PROPIETARIO_ID),
                        List.of(vistaTemporal()));
        when(jdbc.query(anyString(), any(RowMapper.class)))
                .thenReturn(List.of(TipoEstacionamiento.PUBLICO));
        when(resolutor.resolver("CLIENTE", "CLI-0007"))
                .thenReturn(Optional.of(new DestinoRfid1Persistido(
                        "CLIENTE", "CLI-0007", CLIENTE_ID, null, true, "SIN_MEMBRESIA")));
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);

        var resultado = repositorio.confirmarCaptura(
                CAPTURA_ID, PROPIETARIO_ID, 2, 4, HUELLA_SESION, CLAVE_HASH, AHORA);

        assertEquals("CANCELADA", resultado.estado());
        assertEquals("CLIENTE_SIN_MEMBRESIA", resultado.codigoError());
        verify(resolutor).resolver("CLIENTE", "CLI-0007");
        verify(jdbc, never()).queryForObject(anyString(), org.mockito.ArgumentMatchers.eq(Boolean.class), any());
        verify(jdbc, never()).query(org.mockito.ArgumentMatchers.contains("INSERT INTO asociacion_tarjeta_rfid1"),
                any(RowMapper.class), any(Object[].class));
        verify(jdbc).update(org.mockito.ArgumentMatchers.contains("SET estado = ?"), any(Object[].class));
    }

    private static void prepararConfirmacion(
            JdbcTemplate jdbc, ResolutorDestinoRfid1 resolutor, CapturaRfid1Persistida captura) {
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of(captura));
        when(resolutor.resolver("EMPLEADO", "E-0007"))
                .thenReturn(Optional.of(new DestinoRfid1Persistido("EMPLEADO", "E-0007", null, 7L, true)));
    }

    private static RepositorioConfirmacionRfid1Jdbc.VistaTemporal vistaTemporal() {
        return new RepositorioConfirmacionRfid1Jdbc.VistaTemporal(
                "04A1B2C3", HUELLA_UID, AHORA, AHORA.plusSeconds(300));
    }

    private static CapturaRfid1Persistida captura(String estado, String hashConfirmacion,
            String codigoConfirmacion, Long asociacionId) {
        Instant preview = "VISTA_PREVIA".equals(estado) ? AHORA : null;
        return new CapturaRfid1Persistida(
                CAPTURA_ID, "EMPLEADO", "E-0007", null, 7L, PROPIETARIO_ID,
                2, 4, HUELLA_SESION, "b".repeat(64), "d".repeat(64), "0001", HUELLA_UID,
                estado, "COMPLETADA".equals(estado) ? "ASOCIADA" : "PREVIEW_READY", null,
                AHORA.minusSeconds(30), AHORA.plusSeconds(90),
                "COMPLETADA".equals(estado) ? AHORA : null,
                preview, preview == null ? null : preview.plusSeconds(300),
                hashConfirmacion, codigoConfirmacion, asociacionId);
    }

    private static CapturaRfid1Persistida capturaCliente(String estado) {
        Instant preview = "VISTA_PREVIA".equals(estado) ? AHORA : null;
        return new CapturaRfid1Persistida(
                CAPTURA_ID, "CLIENTE", "CLI-0007", CLIENTE_ID, null, PROPIETARIO_ID,
                2, 4, HUELLA_SESION, "b".repeat(64), "d".repeat(64), "0001", HUELLA_UID,
                estado, "PREVIEW_READY", null, AHORA.minusSeconds(30), AHORA.plusSeconds(90), null,
                preview, preview == null ? null : preview.plusSeconds(300),
                null, null, null);
    }
}
