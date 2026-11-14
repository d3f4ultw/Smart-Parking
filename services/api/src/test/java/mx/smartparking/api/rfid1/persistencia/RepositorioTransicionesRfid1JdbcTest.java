package mx.smartparking.api.rfid1.persistencia;

import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.CapturaRfid1Persistida;
import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.ResultadoLecturaRfid1;
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
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class RepositorioTransicionesRfid1JdbcTest {

    private static final Instant AHORA = Instant.parse("2026-10-27T20:00:00Z");
    private static final String CAPTURA_ID = "0a2c3e4f6a8b4c0d9e1f2a3b4c5d6e7f";
    private static final String HUELLA_UID = "a".repeat(64);

    @Test
    void uidNuevoSoloCreaVistaPreviaYAlmacenaElUidTemporal() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioTransicionesRfid1Jdbc repositorio = new RepositorioTransicionesRfid1Jdbc(jdbc);
        prepararCapturaEscaneando(jdbc);
        when(jdbc.queryForObject(anyString(), org.mockito.ArgumentMatchers.eq(Boolean.class), any()))
                .thenReturn(false);
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1, 1);

        ResultadoLecturaRfid1 resultado = repositorio.completarLectura(
                CAPTURA_ID, "0001", "04A1B2C3", HUELLA_UID, AHORA);

        assertEquals("VISTA_PREVIA", resultado.estado());
        assertEquals("PREVIEW_READY", resultado.resultado());
        assertNull(resultado.codigoError());
        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc, times(2)).update(sql.capture(), any(Object[].class));
        assertTrue(sql.getAllValues().stream().anyMatch(consulta ->
                consulta.contains("SET estado = 'VISTA_PREVIA'")));
        assertTrue(sql.getAllValues().stream().anyMatch(consulta ->
                consulta.contains("INSERT INTO uid_temporal_rfid1")));
        assertFalse(sql.getAllValues().stream().anyMatch(consulta ->
                consulta.contains("INSERT INTO asociacion_tarjeta_rfid1")));
    }

    @Test
    void uidHistoricoSeRechazaSinCerrarCapturaNiCrearTemporal() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioTransicionesRfid1Jdbc repositorio = new RepositorioTransicionesRfid1Jdbc(jdbc);
        prepararCapturaEscaneando(jdbc);
        when(jdbc.queryForObject(anyString(), org.mockito.ArgumentMatchers.eq(Boolean.class), any()))
                .thenReturn(true);
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);

        ResultadoLecturaRfid1 resultado = repositorio.completarLectura(
                CAPTURA_ID, "0002", "04A1B2C3", HUELLA_UID, AHORA);

        assertEquals("ESCANEANDO", resultado.estado());
        assertEquals("TARJETA_YA_REGISTRADA", resultado.codigoError());
        assertFalse(resultado.repetida());
        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).update(sql.capture(), any(Object[].class));
        assertTrue(sql.getValue().contains("codigo_error = 'TARJETA_YA_REGISTRADA'"));
        verify(jdbc, never()).update(org.mockito.ArgumentMatchers.contains("uid_temporal_rfid1"), any(Object[].class));
    }

    @Test
    void huellaDeSesionAusenteInvalidaCapturaYDisparaLimpiezaEnLaTransicion() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioTransicionesRfid1Jdbc repositorio = new RepositorioTransicionesRfid1Jdbc(jdbc);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class)))
                .thenReturn(List.of(captura("VISTA_PREVIA")));
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);

        int invalidas = repositorio.invalidarSesionesAusentes(Set.of(), AHORA);

        assertEquals(1, invalidas);
        ArgumentCaptor<String> consulta = ArgumentCaptor.forClass(String.class);
        verify(jdbc).query(consulta.capture(), any(RowMapper.class), any(Object[].class));
        assertTrue(consulta.getValue().contains("creada_en < ?"));
        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).update(sql.capture(), any(Object[].class));
        assertTrue(sql.getValue().contains("estado = ?"));
        assertTrue(sql.getValue().contains("terminada_en = ?"));
    }

    private static void prepararCapturaEscaneando(JdbcTemplate jdbc) {
        when(jdbc.query(anyString(), any(RowMapper.class))).thenReturn(List.of());
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class)))
                .thenReturn(List.of(captura("ESCANEANDO")), List.of(UUID.fromString(
                        "13f989d5-117d-47ce-8845-2cead6cfba44")));
    }

    private static CapturaRfid1Persistida captura(String estado) {
        boolean preview = "VISTA_PREVIA".equals(estado);
        Instant previsualizada = preview ? AHORA.minusSeconds(10) : null;
        return new CapturaRfid1Persistida(
                CAPTURA_ID, "EMPLEADO", "E-0007", null, 7L,
                UUID.fromString("13f989d5-117d-47ce-8845-2cead6cfba44"), 2, 4,
                "c".repeat(64), "d".repeat(64), "a".repeat(64),
                preview ? "000A" : null, preview ? HUELLA_UID : null, estado,
                preview ? "PREVIEW_READY" : null, null, AHORA.minusSeconds(30),
                AHORA.plusSeconds(90), null, previsualizada,
                preview ? previsualizada.plusSeconds(300) : null, null, null, null);
    }
}
