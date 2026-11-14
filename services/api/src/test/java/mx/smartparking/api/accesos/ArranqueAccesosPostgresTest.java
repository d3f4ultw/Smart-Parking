package mx.smartparking.api.accesos;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

/** Inicia Spring y Flyway solo contra la base sintética indicada explícitamente. */
@EnabledIfEnvironmentVariable(named = "SMARTPARKING_POSTGRES_DESCARTABLE", matches = "true")
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.application.name=smartparking-pruebas",
        "spring.profiles.active=pruebas",
        "server.address=127.0.0.1"
})
class ArranqueAccesosPostgresTest {
    private static final String TOKEN_PRUEBA = java.util.UUID.randomUUID().toString();
    @LocalServerPort
    private int puerto;
    @Autowired
    private RepositorioAccesosJdbc repositorio;

    @DynamicPropertySource
    static void configurarBaseDescartable(DynamicPropertyRegistry registro) {
        String host = System.getenv("POSTGRES_HOST");
        String puertoBase = System.getenv("POSTGRES_PORT");
        String base = System.getenv("POSTGRES_DB");
        String usuario = System.getenv("POSTGRES_USER");
        String contrasena = System.getenv("POSTGRES_PASSWORD");
        assertTrue("127.0.0.1".equals(host) || "localhost".equals(host));
        assertEquals("sp_rfid2_horario_test", base);
        assertNotNull(puertoBase);
        assertTrue(puertoBase.matches("[0-9]{1,5}"));
        assertNotNull(usuario);
        assertNotNull(contrasena);
        registro.add("spring.datasource.url", () -> "jdbc:postgresql://" + host + ":" + puertoBase + "/" + base);
        registro.add("spring.datasource.username", () -> usuario);
        registro.add("spring.datasource.password", () -> contrasena);
        registro.add("smartparking.rfid1.token-sha256", () -> {
            try {
                byte[] huella = java.security.MessageDigest.getInstance("SHA-256")
                        .digest(TOKEN_PRUEBA.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                return java.util.HexFormat.of().formatHex(huella);
            } catch (java.security.NoSuchAlgorithmException excepcion) {
                throw new IllegalStateException(excepcion);
            }
        });
    }

    @Test
    void arrancaYProtegeLosEndpoints() throws Exception {
        assertNotNull(repositorio);
        try (HttpClient cliente = HttpClient.newHttpClient()) {
            for (String ruta : new String[] {"/api/v1/accesos/capacidad", "/api/v1/accesos/dentro?pagina=1",
                    "/api/v1/accesos/salidas-manuales/capacidad"}) {
                HttpRequest solicitud = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + puerto + ruta))
                        .GET().build();
                assertEquals(401, cliente.send(solicitud, HttpResponse.BodyHandlers.discarding()).statusCode());
            }
            String tecnico = "http://127.0.0.1:" + puerto + "/api/v1/dispositivos/rfid-3/salidas-manuales/capacidad";
            HttpRequest desafioAnonimo = HttpRequest.newBuilder(URI.create(tecnico + "/desafio")).GET().build();
            assertEquals(401, cliente.send(desafioAnonimo, HttpResponse.BodyHandlers.discarding()).statusCode());
            HttpRequest desafioConToken = HttpRequest.newBuilder(URI.create(tecnico + "/desafio"))
                    .header("Authorization", "Bearer " + TOKEN_PRUEBA).GET().build();
            // Sin clave API–firmware no se emite desafío aunque el Bearer sea correcto.
            assertEquals(503, cliente.send(desafioConToken, HttpResponse.BodyHandlers.discarding()).statusCode());
            HttpRequest desconexionAnonima = HttpRequest.newBuilder(URI.create(tecnico))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString("{\"conectado\":false}")).build();
            assertEquals(401, cliente.send(desconexionAnonima, HttpResponse.BodyHandlers.discarding()).statusCode());
            HttpRequest desconexion = HttpRequest.newBuilder(URI.create(tecnico))
                    .header("Authorization", "Bearer " + TOKEN_PRUEBA).header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString("{\"conectado\":false}")).build();
            assertEquals(204, cliente.send(desconexion, HttpResponse.BodyHandlers.discarding()).statusCode());
        }
    }
}
