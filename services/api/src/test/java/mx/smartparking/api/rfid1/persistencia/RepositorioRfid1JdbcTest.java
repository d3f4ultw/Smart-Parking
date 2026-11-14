package mx.smartparking.api.rfid1.persistencia;

import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.DestinoRfid1Persistido;
import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.NuevaCapturaRfid1;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class RepositorioRfid1JdbcTest {

    private static final Instant AHORA = Instant.parse("2026-10-27T20:00:00Z");
    private static final UUID PROPIETARIO_ID = UUID.fromString("13f989d5-117d-47ce-8845-2cead6cfba44");
    private static final String CAPTURA_ID = "0a2c3e4f6a8b4c0d9e1f2a3b4c5d6e7f";

    @Test
    void capturaNuevaPersisteSoloLaHuellaDeSesion() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioRfid1Jdbc repositorio = repositorio(jdbc);
        NuevaCapturaRfid1 nueva = new NuevaCapturaRfid1(
                CAPTURA_ID, "EMPLEADO", "E-0007", null, 7L, PROPIETARIO_ID,
                2, 4, "c".repeat(64), "a".repeat(64), "b".repeat(64), AHORA, AHORA.plusSeconds(120));
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(0);

        repositorio.insertarCaptura(nueva);

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).update(sql.capture(), any(Object[].class));
        assertTrue(sql.getValue().contains("huella_sesion"));
        assertTrue(sql.getValue().contains("clave_inicio_hash, huella_solicitud"));
        assertFalse(sql.getValue().contains("session_id"));
    }

    @Test
    void elegibilidadSoloConsideraTarjetasActivas() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioRfid1Jdbc repositorio = repositorio(jdbc);
        when(jdbc.queryForObject(anyString(), eq(Boolean.class), any())).thenReturn(false);
        DestinoRfid1Persistido destino = new DestinoRfid1Persistido("EMPLEADO", "E-0007", null, 7L, false);

        boolean tieneTarjetaActiva = repositorio.destinoTieneTarjeta(destino);

        assertFalse(tieneTarjetaActiva);
        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).queryForObject(sql.capture(), eq(Boolean.class), any());
        assertTrue(sql.getValue().contains("estado = 'ACTIVA'"));
    }

    @Test
    void capturaActivaSeFiltraPorSesionYIncluyeLaVentanaDeVistaPrevia() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioRfid1Jdbc repositorio = repositorio(jdbc);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of());

        repositorio.buscarActivaDePropietario(
                PROPIETARIO_ID, 2, 4, "c".repeat(64), AHORA);

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).query(sql.capture(), any(RowMapper.class), any(Object[].class));
        assertTrue(sql.getValue().contains("huella_sesion = ?"));
        assertTrue(sql.getValue().contains("confirmacion_vence_en > ?"));
        assertTrue(sql.getValue().contains("estado = 'VISTA_PREVIA'"));
    }

    @Test
    void reproduccionIdempotenteSeLimitaALaHuellaDeLaSesion() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioRfid1Jdbc repositorio = repositorio(jdbc);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of());

        repositorio.buscarPorIdempotencia(PROPIETARIO_ID, "a".repeat(64), "c".repeat(64));

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object[]> parametros = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).query(sql.capture(), any(RowMapper.class), parametros.capture());
        assertTrue(sql.getValue().contains("huella_sesion = ?"));
        assertTrue(Arrays.asList(parametros.getValue()).contains("c".repeat(64)));
    }

    @Test
    void resolverAdmiteEmpleadoInactivoComoContexto() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        ResolutorDestinoRfid1 resolutor = new ResolutorDestinoRfid1(jdbc);
        DestinoRfid1Persistido destino = new DestinoRfid1Persistido("EMPLEADO", "E-0007", null, 7L, false);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of(destino));

        var resuelto = resolutor.resolver("EMPLEADO", "E-0007");

        assertTrue(resuelto.isPresent());
        assertFalse(resuelto.get().activo());
    }

    private static RepositorioRfid1Jdbc repositorio(JdbcTemplate jdbc) {
        return new RepositorioRfid1Jdbc(jdbc, mock(ResolutorDestinoRfid1.class));
    }
}
