package mx.smartparking.api.empleados;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.persistencia.RepositorioEmpleados.ResultadoPaginaEmpleados;
import mx.smartparking.api.persistencia.RepositorioEmpleadosJdbc;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class RepositorioEmpleadosJdbcTest {

    @Test
    void limitaPaginaSolicitadaAlUltimoBloqueYOrdenaPorIdentificador() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForObject(anyString(), eq(Long.class))).thenReturn(11L);
        Empleado empleado = new Empleado(11, "E-0011", "Ana", "López", null, EstadoEmpleado.ACTIVO, 1);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of(empleado));
        RepositorioEmpleadosJdbc repositorio = new RepositorioEmpleadosJdbc(jdbc);

        ResultadoPaginaEmpleados pagina = repositorio.consultarPagina(99, 10);

        assertEquals(2, pagina.pagina());
        assertEquals(11, pagina.totalRegistros());
        assertEquals(2, pagina.totalPaginas());
        assertEquals(List.of(empleado), pagina.items());
        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).query(sql.capture(), any(RowMapper.class), eq(10), eq(10L));
        assertTrue(sql.getValue().contains("ORDER BY e.id ASC LIMIT ? OFFSET ?"));
        assertTrue(sql.getValue().contains("e.primer_apellido, e.segundo_apellido"));
    }

    @Test
    void buscaPorNombreOCodigoSoloEntreEmpleadosActivosSinCuentaVinculada() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForObject(anyString(), eq(Long.class), any(Object[].class))).thenReturn(1L);
        Empleado empleado = new Empleado(42, "E-0042", "Ana", "López", null, EstadoEmpleado.ACTIVO, 3);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of(empleado));
        RepositorioEmpleadosJdbc repositorio = new RepositorioEmpleadosJdbc(jdbc);

        ResultadoPaginaEmpleados pagina = repositorio.consultarElegiblesParaOperador(1, 10, "E-0042");

        assertEquals(List.of(empleado), pagina.items());
        assertEquals(1, pagina.totalRegistros());
        ArgumentCaptor<String> sqlConteo = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object[]> parametrosConteo = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).queryForObject(sqlConteo.capture(), eq(Long.class), parametrosConteo.capture());
        assertTrue(sqlConteo.getValue().contains("e.estado = 'ACTIVO' AND c.id IS NULL"));
        assertTrue(sqlConteo.getValue().contains("concat_ws(' ', e.nombres, e.primer_apellido, e.segundo_apellido)"));
        assertTrue(sqlConteo.getValue().contains("lpad(e.id::text, 4, '0')"));
        assertEquals("%E-0042%", parametrosConteo.getValue()[0]);
        assertEquals("%E-0042%", parametrosConteo.getValue()[1]);

        ArgumentCaptor<String> sqlFilas = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object[]> parametrosFilas = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).query(sqlFilas.capture(), any(RowMapper.class), parametrosFilas.capture());
        assertTrue(sqlFilas.getValue().contains("ORDER BY e.id ASC LIMIT ? OFFSET ?"));
        assertEquals(10, parametrosFilas.getValue()[2]);
        assertEquals(0L, parametrosFilas.getValue()[3]);
    }

    @Test
    void directorioVacioConservaPaginaUnoYNoEjecutaConsultaDeFilas() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForObject(anyString(), eq(Long.class))).thenReturn(0L);
        RepositorioEmpleadosJdbc repositorio = new RepositorioEmpleadosJdbc(jdbc);

        ResultadoPaginaEmpleados pagina = repositorio.consultarPagina(5, 10);

        assertEquals(1, pagina.pagina());
        assertEquals(0, pagina.totalRegistros());
        assertEquals(0, pagina.totalPaginas());
        assertTrue(pagina.items().isEmpty());
        verify(jdbc, never()).query(anyString(), any(RowMapper.class), any(Object[].class));
    }

    @Test
    void reservaClaveConConflictoAtomicoYSinGuardarLaClaveOriginal() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(0);
        RepositorioEmpleadosJdbc repositorio = new RepositorioEmpleadosJdbc(jdbc);

        boolean reservada = repositorio.reservarRegistro(
                UUID.fromString("d4371739-37af-4746-a862-ae11f5331d62"), "a".repeat(64), "b".repeat(64));

        assertFalse(reservada);
        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).update(sql.capture(), any(Object[].class));
        assertTrue(sql.getValue().contains("ON CONFLICT (cuenta_id, clave_hash) DO NOTHING"));
        assertTrue(sql.getValue().contains("'RESERVADA'"));
    }

    @Test
    void guardaCorreoYNormalizadoEnElRegistroDelEmpleado() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForObject(anyString(), eq(Long.class), any(Object[].class))).thenReturn(42L);
        RepositorioEmpleadosJdbc repositorio = new RepositorioEmpleadosJdbc(jdbc);

        long id = repositorio.crearEmpleado("Ana", "López", null, "Ana@example.test", "ana@example.test");

        assertEquals(42L, id);
        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object[]> parametros = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).queryForObject(sql.capture(), eq(Long.class), parametros.capture());
        assertTrue(sql.getValue().contains("nombres, primer_apellido, segundo_apellido, correo, correo_normalizado"));
        assertEquals(
                Arrays.asList("Ana", "López", null, "Ana@example.test", "ana@example.test"),
                Arrays.asList(parametros.getValue()));
    }
}
