package mx.smartparking.api.persistencia;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class CargadorSqlTest {

    @Test
    void cargaUnRecursoSqlDelClasspathComoFlujoUtf8() {
        String consulta = CargadorSql.cargar("cuentas/crear_dueno.sql");

        assertTrue(consulta.contains("INSERT INTO cuenta"));
        assertTrue(consulta.contains("correo_normalizado"));
    }

    @Test
    void fallaRapidoConLaRutaCuandoElRecursoNoExiste() {
        IllegalStateException excepcion = assertThrows(
                IllegalStateException.class,
                () -> CargadorSql.cargar("cuentas/recurso_ausente.sql"));

        assertTrue(excepcion.getMessage().contains("sql/cuentas/recurso_ausente.sql"));
    }
}
