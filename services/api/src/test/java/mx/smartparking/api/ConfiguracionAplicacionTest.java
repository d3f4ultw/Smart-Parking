package mx.smartparking.api;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.io.InputStream;
import java.util.Properties;
import org.junit.jupiter.api.Test;

class ConfiguracionAplicacionTest {

    @Test
    void requiereVariablesDeEntornoYExponeSaludSinDetalles() throws IOException {
        Properties propiedades = new Properties();

        try (InputStream recurso = getClass().getResourceAsStream("/application.properties")) {
            assertNotNull(recurso, "Debe existir la configuración de Spring Boot.");
            propiedades.load(recurso);
        }

        assertEquals("${SPRING_APPLICATION_NAME}", propiedades.getProperty("spring.application.name"));
        assertEquals("${SPRING_PROFILE}", propiedades.getProperty("spring.profiles.active"));
        assertEquals("${API_BIND_ADDRESS}", propiedades.getProperty("server.address"));
        assertEquals("${API_PORT}", propiedades.getProperty("server.port"));
        assertEquals("${POSTGRES_USER}", propiedades.getProperty("spring.datasource.username"));
        assertEquals("${POSTGRES_PASSWORD}", propiedades.getProperty("spring.datasource.password"));

        String urlJDBC = propiedades.getProperty("spring.datasource.url");
        assertNotNull(urlJDBC, "Debe derivarse la conexión JDBC de la configuración PostgreSQL.");
        assertTrue(urlJDBC.contains("${POSTGRES_HOST}"));
        assertTrue(urlJDBC.contains("${POSTGRES_PORT}"));
        assertTrue(urlJDBC.contains("${POSTGRES_DB}"));

        assertEquals("health", propiedades.getProperty("management.endpoints.web.exposure.include"));
        assertEquals("never", propiedades.getProperty("management.endpoint.health.show-details"));
    }
}
