package mx.smartparking.api.integracion;

import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.etag;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.leerJson;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.texto;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.net.URI;
import java.net.http.HttpResponse;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.Map;
import java.util.UUID;
import mx.smartparking.api.integracion.ApiCliente;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;

/** Verifica por HTTP el replay del ledger de reemisiones migrado desde V6. */
final class OperadoresAdministracionBackfillAceptacionTest {

    private static final String CSRF = "X-CSRF-TOKEN";
    private static final String ASUNTO_INVITACION = "Activa tu cuenta de Smart Parking";
    private static final UUID OPERADOR_PENDIENTE_V6 = UUID.fromString("10000000-0000-4000-8000-000000000002");
    private static final String CORREO_OPERADOR = "pendiente.v6@example.test";
    private static final String CLAVE_REEMISION = "fase2-v6-reemision-replay-2026";

    @Test
    void reproduceLaClaveMigradaSinInsertarAccionNiEnviarCorreo() throws Exception {
        URI apiUrl = OperadoresAdministracionEntornoAceptacion.apiUrl();
        URI mailpitUrl = OperadoresAdministracionEntornoAceptacion.mailpitUrl();
        String correoDueno = System.getenv("TEST_OWNER_EMAIL");
        String contrasenaDueno = System.getenv("TEST_OWNER_PASSWORD");
        assumeTrue(correoDueno != null && correoDueno.endsWith("@example.test")
                        && contrasenaDueno != null && !contrasenaDueno.isBlank(),
                "La aceptación requiere credenciales sintéticas del propietario.");
        OperadoresAdministracionEntornoAceptacion.prepararCredencialDueno(correoDueno, contrasenaDueno);

        ApiCliente dueno = new ApiCliente(apiUrl);
        String csrfInicial = dueno.obtenerCsrf(true);
        HttpResponse<String> login = dueno.postJson("/api/v1/sesion",
                Map.of("correo", correoDueno, "contrasena", contrasenaDueno), Map.of(CSRF, csrfInicial));
        assertEquals(200, login.statusCode());
        String csrf = texto(leerJson(login.body()), "csrfToken");
        dueno.csrf(csrf);

        HttpResponse<String> detalle = dueno.get("/api/v1/operadores/" + OPERADOR_PENDIENTE_V6);
        assertEquals(200, detalle.statusCode());
        String revision = etag(detalle);
        assertEquals(1, contarReemisiones(OPERADOR_PENDIENTE_V6),
                "V7 debe conservar la única acción creada por el backfill de V6.");
        assertEquals(0, MailpitApiCliente.textosPorAsunto(mailpitUrl, ASUNTO_INVITACION, CORREO_OPERADOR).size());

        HttpResponse<String> replay = dueno.postJson(
                "/api/v1/operadores/" + OPERADOR_PENDIENTE_V6 + "/invitacion/reemitir", null,
                Map.of(CSRF, csrf, "If-Match", revision, "Idempotency-Key", CLAVE_REEMISION));

        assertEquals(200, replay.statusCode());
        JsonNode respuesta = leerJson(replay.body());
        assertEquals("ENVIADO", texto(respuesta, "estadoInvitacion"));
        assertEquals(1, contarReemisiones(OPERADOR_PENDIENTE_V6),
                "El replay del ledger migrado no debe insertar otra acción.");
        assertEquals(0, MailpitApiCliente.textosPorAsunto(mailpitUrl, ASUNTO_INVITACION, CORREO_OPERADOR).size(),
                "El replay del ledger migrado no debe enviar otra invitación.");
    }

    private static int contarReemisiones(UUID operadorId) throws Exception {
        try (Connection conexion = DriverManager.getConnection(System.getenv("TEST_DATABASE_URL"),
                System.getenv("TEST_DATABASE_USER"), System.getenv("TEST_DATABASE_PASSWORD"));
                PreparedStatement consulta = conexion.prepareStatement(
                        "SELECT count(*) FROM idempotencia_accion_operador "
                                + "WHERE operador_id = ? AND operacion = 'REEMITIR_INVITACION'")) {
            consulta.setObject(1, operadorId);
            try (ResultSet resultado = consulta.executeQuery()) {
                assertTrue(resultado.next());
                return resultado.getInt(1);
            }
        }
    }
}
