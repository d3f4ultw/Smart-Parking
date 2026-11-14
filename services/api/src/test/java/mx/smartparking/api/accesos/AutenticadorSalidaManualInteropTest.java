package mx.smartparking.api.accesos;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Contrasta el protocolo Java con un vector independiente generado por Python. */
@EnabledIfEnvironmentVariable(named = "SMARTPARKING_MANUAL_INTEROP_DESCARTABLE", matches = "true")
class AutenticadorSalidaManualInteropTest {
    @Test
    void aceptaVectorPythonSinRevelarClaveNiFirmas() throws Exception {
        byte[] clave = Files.readAllBytes(Path.of(System.getenv("SMARTPARKING_MANUAL_CLAVE_PRUEBA")));
        JsonNode vector = new ObjectMapper().readTree(Files.readAllBytes(
                Path.of(System.getenv("SMARTPARKING_MANUAL_VECTOR_PRUEBA"))));
        AutenticadorSalidaManual autenticador = new AutenticadorSalidaManual(HexFormat.of().formatHex(clave));
        UUID operacion = UUID.fromString(vector.path("operacionId").asText());
        String boot = vector.path("bootId").asText();
        String ticket = vector.path("ticketId").asText();
        byte[] esperado = vector.path("firmaExec").asText().getBytes(StandardCharsets.US_ASCII);
        byte[] recibido = autenticador.firmarEjecucion(operacion, boot, ticket).getBytes(StandardCharsets.US_ASCII);
        assertTrue(MessageDigest.isEqual(esperado, recibido));
        assertTrue(autenticador.verificarResultado(operacion, boot, ticket, "EJECUTADA",
                vector.path("firmaResultadoE").asText()));
        assertTrue(autenticador.verificarResultado(operacion, boot, ticket, "NO_EJECUTADA",
                vector.path("firmaResultadoN").asText()));
        assertFalse(autenticador.verificarResultado(operacion, boot, ticket, "NO_EJECUTADA",
                vector.path("firmaResultadoE").asText()));
        JsonNode prueba = new ObjectMapper().readTree(Files.readAllBytes(
                Path.of(System.getenv("SMARTPARKING_MANUAL_PROBE_VECTOR"))));
        assertTrue(autenticador.verificarPrueba(prueba.path("bootId").asText(), prueba.path("nonce").asText(),
                prueba.path("firmaProbe").asText()));
        assertFalse(autenticador.verificarPrueba(prueba.path("bootId").asText(), prueba.path("nonce").asText(), null));
    }
}
