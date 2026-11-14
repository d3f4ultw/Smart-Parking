package mx.smartparking.api.persistencia;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.LocalTime;
import java.util.Optional;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.configuracion.DatosConfiguracion;
import mx.smartparking.api.configuracion.DatosPropietario;
import mx.smartparking.api.configuracion.HorarioConfiguracion;
import mx.smartparking.api.configuracion.ModoHorario;
import mx.smartparking.api.configuracion.TipoEstacionamiento;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class RepositorioConfiguracionJdbcTest {

    @Test
    void lecturaDeConfiguracionProyectaPerfilYCorreoDesdeCuentaVinculada() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        when(jdbcTemplate.query(anyString(), any(RowMapper.class))).thenReturn(List.of());
        RepositorioConfiguracionJdbc repositorio = new RepositorioConfiguracionJdbc(jdbcTemplate);

        Optional<ConfiguracionPersistida> encontrada = repositorio.buscar();

        assertTrue(encontrada.isEmpty());
        ArgumentCaptor<String> consulta = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).query(consulta.capture(), any(RowMapper.class));
        String sql = consulta.getValue();
        assertTrue(sql.contains("LEFT JOIN cuenta a ON a.id = c.dueno_cuenta_id"));
        assertTrue(sql.contains("a.nombres AS propietario_nombres"));
        assertTrue(sql.contains("a.correo AS correo_propietario"));
    }

    @Test
    void mutacionesDePanelYTransferenciaConservanLaIdentidadDelEstacionamiento() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        when(jdbcTemplate.update(anyString(), any(Object[].class))).thenReturn(1);
        RepositorioConfiguracionJdbc repositorio = new RepositorioConfiguracionJdbc(jdbcTemplate);
        HorarioConfiguracion horario = new HorarioConfiguracion(
                ModoHorario.INTERVALO_DIARIO,
                "America/Mexico_City",
                LocalTime.of(22, 0),
                LocalTime.of(6, 0));
        DatosConfiguracion datos = new DatosConfiguracion(
                new DatosPropietario(
                        "Ana", "López", null, "ana@example.test", "Acceso seguro 2026", "Administracion segura 2026"),
                "Centro Nuevo",
                TipoEstacionamiento.MIXTO,
                horario);

        repositorio.renombrar("Centro Nuevo", 6, UUID.randomUUID(), "hash-renombre");
        repositorio.actualizarDatosEstacionamiento(
                TipoEstacionamiento.MIXTO, horario, 7, UUID.randomUUID(), "hash-horario");
        repositorio.completarTransferencia(
                datos, "hash-admin", UUID.randomUUID(), 13, 11, UUID.randomUUID(), "hash-completar");

        ArgumentCaptor<String> consultas = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate, times(3)).update(consultas.capture(), any(Object[].class));
        List<String> sentencias = consultas.getAllValues();

        assertEquals(3, sentencias.size());
        assertFalse(sentencias.stream().anyMatch(sql -> sql.matches("(?is).*\\bestacionamiento_id\\s*=.*")));
        assertTrue(sentencias.get(0).contains("WHERE id = 1 AND estado = 'CONFIGURADA'"));
        assertTrue(sentencias.get(1).contains("WHERE id = 1 AND estado = 'CONFIGURADA'"));
        assertTrue(sentencias.get(2).contains("WHERE id = 1 AND estado = 'TRANSFERENCIA_PENDIENTE'"));
    }
}
