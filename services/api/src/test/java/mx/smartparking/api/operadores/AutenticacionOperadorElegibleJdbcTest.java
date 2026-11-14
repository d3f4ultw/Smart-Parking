package mx.smartparking.api.operadores;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.List;
import mx.smartparking.api.persistencia.ProveedorCredencialesPropietarioJdbc;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

/** Verifica la consulta JDBC de credenciales para DUENO y OPERADOR elegible. */
class AutenticacionOperadorElegibleJdbcTest {

    @Test
    void consultaDuenoConfiguradoYOperadorConEmpleadoActivo() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of());
        ProveedorCredencialesPropietarioJdbc proveedor = new ProveedorCredencialesPropietarioJdbc(jdbc);

        proveedor.buscarPorCorreo(" operador@example.test ");

        ArgumentCaptor<String> consulta = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object[]> parametros = ArgumentCaptor.forClass(Object[].class);
        verifyQuery(jdbc, consulta, parametros);
        String sql = consulta.getValue();
        assertTrue(sql.contains("a.rol = 'DUENO'"));
        assertTrue(sql.contains("a.estado = 'ACTIVA'"));
        assertTrue(sql.contains("a.id = c.dueno_cuenta_id"));
        assertTrue(sql.contains("UNION ALL"));
        assertTrue(sql.contains("WHERE a.rol = 'OPERADOR' AND a.estado = 'ACTIVA'"));
        assertTrue(sql.contains("JOIN empleado e ON e.id = a.empleado_id"));
        assertTrue(sql.contains("e.estado = 'ACTIVO'"));
        assertTrue(sql.contains("a.hash_contrasena_acceso IS NOT NULL"));
        assertArrayEquals(new Object[] {"operador@example.test", "operador@example.test"}, parametros.getValue());
    }

    private static void verifyQuery(
            JdbcTemplate jdbc, ArgumentCaptor<String> consulta, ArgumentCaptor<Object[]> parametros) {
        Mockito.verify(jdbc).query(consulta.capture(), any(RowMapper.class), parametros.capture());
    }
}
