package mx.smartparking.api.empleados;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.List;
import mx.smartparking.api.persistencia.RepositorioEmpleadosOperadorJdbc;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class RepositorioEmpleadosOperadorJdbcTest {

    @Test
    void bloqueaEmpleadoConBloqueoDeFila() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of());
        RepositorioEmpleadosOperadorJdbc repositorio = new RepositorioEmpleadosOperadorJdbc(jdbc);

        assertTrue(repositorio.bloquearPorId(42).isEmpty());

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).query(sql.capture(), any(RowMapper.class), any(Object[].class));
        assertTrue(sql.getValue().contains("WHERE id = ? FOR UPDATE"));
    }

    @Test
    void cambiaCorreoSoloConRevisionVigente() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);
        RepositorioEmpleadosOperadorJdbc repositorio = new RepositorioEmpleadosOperadorJdbc(jdbc);

        assertTrue(repositorio.actualizarCorreoYRevision(42, "ana@example.test", "ana@example.test", 7));

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object[]> parametros = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).update(sql.capture(), parametros.capture());
        assertTrue(sql.getValue().contains("WHERE id = ? AND revision = ?"));
        assertTrue(sql.getValue().contains("revision < 9223372036854775807"));
        assertTrue(sql.getValue().contains("revision = revision + 1"));
        assertArrayEquals(new Object[] {"ana@example.test", "ana@example.test", 42L, 7L}, parametros.getValue());
    }

    @Test
    void noIncrementaUnaRevisionObsoleta() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(0);
        RepositorioEmpleadosOperadorJdbc repositorio = new RepositorioEmpleadosOperadorJdbc(jdbc);

        assertFalse(repositorio.actualizarEstadoYRevision(42, "INACTIVO", 6));

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).update(sql.capture(), any(Object[].class));
        assertTrue(sql.getValue().contains("WHERE id = ? AND revision = ?"));
    }

    @Test
    void incrementoDeRevisionUsaCompareAndSet() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(0);
        RepositorioEmpleadosOperadorJdbc repositorio = new RepositorioEmpleadosOperadorJdbc(jdbc);

        assertFalse(repositorio.incrementarRevision(42, 7));

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).update(sql.capture(), any(Object[].class));
        assertTrue(sql.getValue().contains("WHERE id = ? AND revision = ?"));
        assertTrue(sql.getValue().contains("revision < 9223372036854775807"));
    }
}
