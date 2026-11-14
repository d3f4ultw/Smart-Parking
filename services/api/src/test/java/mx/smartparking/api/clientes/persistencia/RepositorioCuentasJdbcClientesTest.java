package mx.smartparking.api.clientes.persistencia;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.persistencia.RepositorioCuentasJdbc;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.http.HttpStatus;
import org.mockito.ArgumentCaptor;

class RepositorioCuentasJdbcClientesTest {

    @Test
    void registroCreaCuentaActivaYUsaCorreoNormalizadoComoIdentidad() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);
        RepositorioCuentasJdbc repositorio = new RepositorioCuentasJdbc(jdbc);

        repositorio.crearCliente("Ana", "López", null, "ana@example.test", "hash-cliente");

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object[]> parametros = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).update(sql.capture(), parametros.capture());
        assertTrue(sql.getValue().contains("'CLIENTE', 'ACTIVA'"));
        assertEquals("ana@example.test", parametros.getValue()[4]);
        assertEquals("ana@example.test", parametros.getValue()[5]);
        assertEquals("hash-cliente", parametros.getValue()[6]);
    }

    @Test
    void conflictoPorIndiceUnicoSeMapeaSinRevelarElCorreo() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.update(anyString(), any(Object[].class))).thenThrow(new DuplicateKeyException("detalle interno"));
        RepositorioCuentasJdbc repositorio = new RepositorioCuentasJdbc(jdbc);

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> repositorio.crearCliente("Ana", "López", null, "ana@example.test", "hash-cliente"));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertEquals("REGISTRO_NO_COMPLETADO", error.codigo());
        assertFalse(error.getMessage().contains("ana@example.test"));
        assertFalse(error.getMessage().contains("detalle interno"));
    }

    @Test
    void cambioDeContrasenaActualizaSoloClienteActivoConRevisionEsperada() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);
        RepositorioCuentasJdbc repositorio = new RepositorioCuentasJdbc(jdbc);
        java.util.UUID id = java.util.UUID.randomUUID();

        boolean actualizado = repositorio.actualizarContrasenaCliente(id, 7, "hash-nuevo");

        assertTrue(actualizado);
        verify(jdbc).update(contains("rol = 'CLIENTE' AND estado = 'ACTIVA' AND revision_acceso = ?"),
                any(Object[].class));
        verify(jdbc).update(contains("revision_acceso = revision_acceso + 1"), any(Object[].class));
    }

    @Test
    void revisionObsoletaNoSeConsideraActualizada() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(0);
        RepositorioCuentasJdbc repositorio = new RepositorioCuentasJdbc(jdbc);

        assertFalse(repositorio.actualizarContrasenaCliente(java.util.UUID.randomUUID(), 7, "hash-nuevo"));
    }
}
