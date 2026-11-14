package mx.smartparking.api.seguridad;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

import java.io.IOException;
import java.io.InputStream;
import java.util.Properties;
import org.junit.jupiter.api.Test;

class ConfiguracionCookieSesionTest {

    @Test
    void conservaCookiesHttpOnlySameSiteStrictYTiempoDeSesionAcotado() throws IOException {
        Properties propiedades = new Properties();
        try (InputStream flujo = getClass().getResourceAsStream("/application.properties")) {
            assertNotNull(flujo, "Debe existir la configuración de la API en el classpath.");
            propiedades.load(flujo);
        }

        assertEquals("30m", valorPorDefecto(propiedades.getProperty("server.servlet.session.timeout")));
        assertEquals("true", propiedades.getProperty("server.servlet.session.cookie.http-only"));
        assertEquals("strict", propiedades.getProperty("server.servlet.session.cookie.same-site"));
        assertEquals("cookie", propiedades.getProperty("server.servlet.session.tracking-modes"));
        assertEquals("false", valorPorDefecto(propiedades.getProperty("server.servlet.session.cookie.secure")));
    }

    private String valorPorDefecto(String valor) {
        assertNotNull(valor);
        if (!valor.startsWith("${")) {
            return valor;
        }
        int separador = valor.indexOf(':');
        int cierre = valor.lastIndexOf('}');
        if (separador < 0 || cierre < separador) {
            return valor;
        }
        return valor.substring(separador + 1, cierre);
    }
}
