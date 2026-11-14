package mx.smartparking.api.persistencia;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.sql.Timestamp;
import java.util.UUID;
import mx.smartparking.api.configuracion.DatosConfiguracion;
import mx.smartparking.api.configuracion.DatosPropietario;
import mx.smartparking.api.configuracion.HorarioConfiguracion;
import mx.smartparking.api.configuracion.ModoHorario;
import mx.smartparking.api.configuracion.TipoEstacionamiento;
import org.mockito.ArgumentCaptor;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

class RepositorioCuentasJdbcTest {

    @Test
    void enlazaTimestampsJDBCConTipoTimestamp() {
        JdbcTemplate jdbc = org.mockito.Mockito.mock(JdbcTemplate.class);
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);
        Instant ahora = Instant.parse("2026-10-25T08:00:00Z");
        RepositorioCuentasJdbc repositorio = new RepositorioCuentasJdbc(jdbc, Clock.fixed(ahora, ZoneOffset.UTC));
        DatosConfiguracion datos = new DatosConfiguracion(
                new DatosPropietario("Ana", "López", null, "ana@example.test", "acceso-seguro", "admin-seguro"),
                "Centro", TipoEstacionamiento.PUBLICO,
                new HorarioConfiguracion(ModoHorario.CONTINUO_24_7, "UTC", null, null));

        repositorio.crearDueno(datos, "hash-acceso");

        ArgumentCaptor<Object[]> parametros = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).update(anyString(), parametros.capture());
        assertEquals(Timestamp.from(ahora), parametros.getValue()[7]);
        assertEquals(Timestamp.from(ahora), parametros.getValue()[8]);
    }

    @Test
    void validaCuentaOperadorSinExigirQueSeaElDuenoActual() {
        JdbcTemplate jdbc = org.mockito.Mockito.mock(JdbcTemplate.class);
        when(jdbc.queryForObject(any(String.class), eq(Integer.class), any(), any(), any(), any(), any()))
                .thenReturn(1);
        RepositorioCuentasJdbc repositorio = new RepositorioCuentasJdbc(jdbc);

        assertTrue(repositorio.sesionVigente(UUID.randomUUID(), 2, "OPERADOR", 99));

        ArgumentCaptor<String> consulta = ArgumentCaptor.forClass(String.class);
        verify(jdbc).queryForObject(consulta.capture(), eq(Integer.class),
                any(), eq(2L), eq("OPERADOR"), eq("OPERADOR"), eq(99L));
        assertTrue(consulta.getValue().contains("(? <> 'DUENO' OR EXISTS"));
        assertTrue(consulta.getValue().contains("a.rol <> 'OPERADOR' OR EXISTS"));
        assertTrue(consulta.getValue().contains("e.estado = 'ACTIVO'"));
    }
}
