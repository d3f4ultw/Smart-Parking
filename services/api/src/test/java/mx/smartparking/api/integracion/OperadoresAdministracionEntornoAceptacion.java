package mx.smartparking.api.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.net.URI;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.util.Locale;
import java.util.UUID;
import mx.smartparking.api.seguridad.ConfiguracionSeguridadPropietario;
import org.springframework.security.crypto.password.PasswordEncoder;

/** Valida que las aceptaciones de operadores solo apunten a servicios del overlay temporal. */
final class OperadoresAdministracionEntornoAceptacion {

    private static final UUID ID_DUENO_SINTETICO = UUID.fromString("00000000-0000-4000-8000-000000000001");

    private OperadoresAdministracionEntornoAceptacion() {
    }

    static URI apiUrl() {
        return servicio("smartparking.api-url", "api", 8080);
    }

    static URI apiSmtpFallidoUrl() {
        return servicio("smartparking.api-url", "api-smtp-fallido", 8080);
    }

    static URI mailpitUrl() {
        return servicio("smartparking.mailpit-url", "mailpit", 8025);
    }

    static void prepararCredencialDueno(String correo, String contrasena) throws SQLException {
        assumeTrue(Boolean.parseBoolean(System.getProperty("smartparking.integration.disposable", "false")),
                "Aceptación omitida: requiere un proyecto de servicios descartables.");
        assertEquals("test", System.getProperty("smartparking.integration.profile"),
                "La aceptación solo admite una base del profile test.");
        assumeTrue(correo != null && correo.endsWith("@example.test")
                        && contrasena != null && !contrasena.isBlank(),
                "La aceptación requiere credenciales sintéticas del propietario.");

        String url = System.getenv("TEST_DATABASE_URL");
        String usuario = System.getenv("TEST_DATABASE_USER");
        String claveBaseDatos = System.getenv("TEST_DATABASE_PASSWORD");
        assertTrue(url != null && url.matches("jdbc:postgresql://db:5432/[A-Za-z0-9_-]+"),
                "La aceptación solo admite la base interna db del proyecto descartable.");
        assumeTrue(usuario != null && !usuario.isBlank() && claveBaseDatos != null,
                "La aceptación requiere credenciales de la base descartable.");

        PasswordEncoder codificador = new ConfiguracionSeguridadPropietario().passwordEncoder();
        String hash = codificador.encode(contrasena);
        try (Connection conexion = DriverManager.getConnection(url, usuario, claveBaseDatos);
                PreparedStatement actualizacion = conexion.prepareStatement("""
                        UPDATE cuenta SET hash_contrasena_acceso = ?
                        WHERE id = ? AND rol = 'DUENO' AND estado = 'ACTIVA' AND correo_normalizado = ?
                        """)) {
            actualizacion.setString(1, hash);
            actualizacion.setObject(2, ID_DUENO_SINTETICO);
            actualizacion.setString(3, correo.strip().toLowerCase(Locale.ROOT));
            assertEquals(1, actualizacion.executeUpdate(),
                    "Solo debe existir el propietario sintético configurado para esta aceptación.");
        }
    }

    private static URI servicio(String propiedad, String hostEsperado, int puertoEsperado) {
        assumeTrue(Boolean.parseBoolean(System.getProperty("smartparking.integration.disposable", "false")),
                "Aceptación omitida: requiere un proyecto de servicios descartables.");
        assertEquals("test", System.getProperty("smartparking.integration.profile"),
                "La aceptación solo admite API y dependencias con profile test.");
        String valor = System.getProperty(propiedad);
        assertTrue(valor != null && !valor.isBlank(), "Falta la URL interna requerida para la aceptación.");
        URI base;
        try {
            base = URI.create(valor.strip());
        } catch (IllegalArgumentException excepcion) {
            throw new AssertionError("La URL interna configurada no es válida.");
        }
        assertEquals("http", base.getScheme(), "Los servicios del overlay usan HTTP dentro de su red privada.");
        assertEquals(hostEsperado, base.getHost(), "La aceptación debe usar el hostname del servicio esperado.");
        assertEquals(puertoEsperado, base.getPort(), "La aceptación debe usar el puerto interno del servicio.");
        assertTrue(base.getUserInfo() == null && base.getQuery() == null && base.getFragment() == null
                        && (base.getPath().isEmpty() || "/".equals(base.getPath())),
                "La URL no debe incluir credenciales, ruta, consulta ni fragmento.");
        return base;
    }
}
