package mx.smartparking.api.rfid1.persistencia;

import static mx.smartparking.api.rfid1.persistencia.RepositorioTarjetasRfid.CandidatoRfid1Persistido;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class RepositorioTarjetasRfidJdbcTest {

    private static final Instant AHORA = Instant.parse("2026-10-27T20:00:00Z");
    private static final long ASOCIACION_ID = 43L;
    private static final UUID CLIENTE_ID = UUID.fromString("c12d1bef-8974-4ff3-9cf9-0f7a0844c39b");

    private static CandidatoRfid1Persistido candidato(String tipo, String codigo) {
        return new CandidatoRfid1Persistido(tipo, codigo, "Persona Prueba", "ACTIVO", false);
    }

    @Test
    void busquedaAcotaResultadosYIncluyeElegibilidadDeTarjetaActiva() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioTarjetasRfidJdbc repositorio = new RepositorioTarjetasRfidJdbc(jdbc);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of());

        repositorio.buscarPersonas("CLIENTE", "Val", 50);

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object[]> parametros = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).query(sql.capture(), any(RowMapper.class), parametros.capture());
        assertTrue(sql.getValue().contains("tiene_activa"));
        assertTrue(sql.getValue().contains("estado_membresia"));
        assertTrue(sql.getValue().contains("LEFT JOIN LATERAL"));
        assertTrue(sql.getValue().contains("'SIN_MEMBRESIA'"));
        assertTrue(sql.getValue().contains("stripe_subscription_id DESC"));
        assertTrue(sql.getValue().contains("ORDER BY codigo.numero ASC LIMIT ?"));
        assertEquals(10, parametros.getValue()[1]);
    }

    @Test
    void consultaVaciaNoDevuelvePersonasNiHaceSQL() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioTarjetasRfidJdbc repositorio = new RepositorioTarjetasRfidJdbc(jdbc);

        assertTrue(repositorio.buscarPersonas("CLIENTE", " ", 10).isEmpty());

        verify(jdbc, never()).query(anyString(), any(RowMapper.class), any(Object[].class));
    }

    @Test
    void busquedaMixtaIntercalaTiposConOrdenEstableYLimiteTotal() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioTarjetasRfidJdbc repositorio = new RepositorioTarjetasRfidJdbc(jdbc);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of(
                candidato("CLIENTE", "CLI-0001"), candidato("EMPLEADO", "E-0001"),
                candidato("CLIENTE", "CLI-0002")));

        var candidatos = repositorio.buscarPersonas("MIXTO", "Ana", 50);

        assertEquals(List.of("CLIENTE", "EMPLEADO", "CLIENTE"), candidatos.stream()
                .map(candidato -> candidato.tipoEntidad()).toList());
        ArgumentCaptor<String> consulta = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object[]> parametros = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).query(consulta.capture(), any(RowMapper.class), parametros.capture());
        assertTrue(consulta.getValue().contains("UNION ALL"));
        assertTrue(consulta.getValue().contains("PARTITION BY tipo_entidad ORDER BY numero ASC"));
        assertTrue(consulta.getValue().contains(
                "ORDER BY orden_tipo ASC, tipo_entidad ASC, numero ASC"));
        assertEquals(10, parametros.getValue()[1]);
        assertEquals(10, parametros.getValue()[3]);
        assertEquals(10, parametros.getValue()[4]);
    }

    @Test
    void directorioMixtoIncluyeAmbosTiposYConservaLaPaginacion() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioTarjetasRfidJdbc repositorio = new RepositorioTarjetasRfidJdbc(jdbc);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of());
        when(jdbc.queryForObject(anyString(), eq(Long.class), any(Object[].class))).thenReturn(12L);

        repositorio.listarTarjetas("MIXTO", "TODAS", "", 20, 10);
        repositorio.contarTarjetas("MIXTO", "TODAS", "");

        ArgumentCaptor<String> consultaPagina = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object[]> parametrosPagina = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).query(consultaPagina.capture(), any(RowMapper.class), parametrosPagina.capture());
        assertTrue(consultaPagina.getValue().contains(
                "(tarjeta.cliente_id IS NOT NULL OR tarjeta.empleado_id IS NOT NULL)"));
        assertTrue(consultaPagina.getValue().contains("LIMIT ? OFFSET ?"));
        assertEquals(10, parametrosPagina.getValue()[4]);
        assertEquals(20, parametrosPagina.getValue()[5]);
        ArgumentCaptor<String> consultaConteo = ArgumentCaptor.forClass(String.class);
        verify(jdbc).queryForObject(consultaConteo.capture(), eq(Long.class), any(Object[].class));
        assertTrue(consultaConteo.getValue().contains(
                "(tarjeta.cliente_id IS NOT NULL OR tarjeta.empleado_id IS NOT NULL)"));
    }

    @Test
    void directorioTrataComodinesComoTextoEnConteoYPagina() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioTarjetasRfidJdbc repositorio = new RepositorioTarjetasRfidJdbc(jdbc);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of());
        when(jdbc.queryForObject(anyString(), eq(Long.class), any(Object[].class))).thenReturn(0L);

        repositorio.listarTarjetas("CLIENTE", "ACTIVA", "A!_%\\", 0, 10);
        repositorio.contarTarjetas("CLIENTE", "ACTIVA", "A!_%\\");

        ArgumentCaptor<Object[]> parametrosPagina = ArgumentCaptor.forClass(Object[].class);
        ArgumentCaptor<Object[]> parametrosConteo = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).query(anyString(), any(RowMapper.class), parametrosPagina.capture());
        verify(jdbc).queryForObject(anyString(), eq(Long.class), parametrosConteo.capture());
        assertEquals("%A!!!_!%\\%", parametrosPagina.getValue()[1]);
        assertEquals(parametrosPagina.getValue()[1], parametrosConteo.getValue()[1]);
    }

    @Test
    void consultasDeOperadorOmitenUidYNoLoIncluyenEnElFiltroDeBusqueda() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioTarjetasRfidJdbc repositorio = new RepositorioTarjetasRfidJdbc(jdbc);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of());
        when(jdbc.queryForObject(anyString(), eq(Long.class), any(Object[].class))).thenReturn(0L);

        repositorio.listarTarjetas("MIXTO", "TODAS", "04A1B2C3", 0, 10, false);
        repositorio.contarTarjetas("MIXTO", "TODAS", "04A1B2C3", false);
        repositorio.buscarTarjeta(ASOCIACION_ID, false);

        ArgumentCaptor<String> consultasLista = ArgumentCaptor.forClass(String.class);
        verify(jdbc, org.mockito.Mockito.times(2)).query(
                consultasLista.capture(), any(RowMapper.class), any(Object[].class));
        assertTrue(consultasLista.getAllValues().getFirst().contains("NULL::text AS uid_canonico"));
        assertTrue(consultasLista.getAllValues().getFirst().contains("CASE WHEN tarjeta.cliente_id IS NOT NULL"));
        assertFalse(consultasLista.getAllValues().getFirst().contains("tarjeta.uid_canonico"));

        ArgumentCaptor<String> consultaConteo = ArgumentCaptor.forClass(String.class);
        verify(jdbc).queryForObject(consultaConteo.capture(), eq(Long.class), any(Object[].class));
        assertTrue(consultaConteo.getValue().contains("CASE WHEN tarjeta.cliente_id IS NOT NULL"));
        assertFalse(consultaConteo.getValue().contains("uid_canonico"));

        assertTrue(consultasLista.getAllValues().get(1).contains("NULL::text AS uid_canonico"));
        assertFalse(consultasLista.getAllValues().get(1).contains("tarjeta.uid_canonico"));
    }

    @Test
    void cancelacionBloqueaPersonaAntesDeTarjetaYConservaHistorial() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioTarjetasRfidJdbc repositorio = new RepositorioTarjetasRfidJdbc(jdbc);
        doReturn(List.of(new RepositorioTarjetasRfidJdbc.DestinoTarjeta(CLIENTE_ID, null)),
                List.of(CLIENTE_ID), List.of("ACTIVA"))
                .when(jdbc).query(anyString(), any(RowMapper.class), any(Object[].class));
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);

        var resultado = repositorio.cancelarTarjeta(ASOCIACION_ID, AHORA);

        assertEquals("CANCELADA", resultado.estado());
        ArgumentCaptor<String> consultas = ArgumentCaptor.forClass(String.class);
        verify(jdbc, org.mockito.Mockito.times(3)).query(
                consultas.capture(), any(RowMapper.class), any(Object[].class));
        assertTrue(consultas.getAllValues().get(1).contains("FOR UPDATE OF codigo, cuenta"));
        assertTrue(consultas.getAllValues().get(2).contains("FOR UPDATE"));
        ArgumentCaptor<String> actualizacion = ArgumentCaptor.forClass(String.class);
        verify(jdbc).update(actualizacion.capture(), any(Object[].class));
        assertTrue(actualizacion.getValue().contains("SET estado = 'CANCELADA', cancelada_en = ?"));
    }

    @Test
    void cancelacionRepetidaDevuelveElEstadoFinalSinActualizarLaFila() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        RepositorioTarjetasRfidJdbc repositorio = new RepositorioTarjetasRfidJdbc(jdbc);
        doReturn(List.of(new RepositorioTarjetasRfidJdbc.DestinoTarjeta(CLIENTE_ID, null)),
                List.of(CLIENTE_ID), List.of("CANCELADA"))
                .when(jdbc).query(anyString(), any(RowMapper.class), any(Object[].class));

        var resultado = repositorio.cancelarTarjeta(ASOCIACION_ID, AHORA);

        assertEquals("CANCELADA", resultado.estado());
        assertTrue(resultado.repetida());
        verify(jdbc, never()).update(anyString(), any(Object[].class));
    }
}
