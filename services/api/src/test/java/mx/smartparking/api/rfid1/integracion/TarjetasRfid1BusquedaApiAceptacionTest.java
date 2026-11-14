package mx.smartparking.api.rfid1.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.net.URLEncoder;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import tools.jackson.databind.JsonNode;

/** Verifica el contrato HTTP del directorio con datos y PostgreSQL descartables. */
@ExtendWith(OutputCaptureExtension.class)
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@EnabledIfSystemProperty(named = "smartparking.integration.disposable", matches = "true")
class TarjetasRfid1BusquedaApiAceptacionTest extends TarjetasRfid1Stage1TestSupport {
    private static final Timestamp INSTANTE = Timestamp.from(Instant.parse("2026-11-09T12:00:00Z"));

    @Test
    void buscaYCuentaElHistorialConFiltrosYOrdenEstable(CapturedOutput salida) throws Exception {
        Persona cliente = crearCliente("buscarcliente");
        String uidCliente = "AA11BB22";
        asociarCliente(uidCliente, cliente.clienteId);
        Persona empleadoCancelado = crearEmpleado("buscarcancelado");
        long cancelada = asociarEmpleado("CC11DD22", empleadoCancelado.id);
        assertEquals(200, dueno.post("/api/v1/tarjetas-rfid/" + cancelada + "/cancelacion", null,
                Map.of(CSRF, dueno.csrf())).statusCode());

        List<Long> asociaciones = new ArrayList<>();
        for (int indice = 0; indice < 12; indice++) {
            Persona empleado = crearEmpleado("lotebusqueda" + indice);
            asociaciones.add(asociarEmpleado(String.format(Locale.ROOT, "B0%06X", indice), empleado.id));
        }

        var porNombre = consultar("MIXTO", "TODAS", 1, "BUSCARCLIENTE");
        assertEquals(1, porNombre.path("total").asInt());
        assertEquals(cliente.codigo, porNombre.path("items").get(0).path("codigoPersona").asText());
        assertEquals(1, consultar("CLIENTE", "TODAS", 1, cliente.codigo.toLowerCase(Locale.ROOT))
                .path("total").asInt());
        assertEquals(1, consultar("MIXTO", "TODAS", 1, "aa11bb")
                .path("total").asInt());
        var canceladas = consultar("EMPLEADO", "CANCELADA", 1, "buscarcancelado");
        assertEquals(1, canceladas.path("total").asInt());
        assertEquals("CANCELADA", canceladas.path("items").get(0).path("estado").asText());
        assertEquals(0, consultar("CLIENTE", "CANCELADA", 1, "buscarcancelado").path("total").asInt());

        var primera = consultar("MIXTO", "TODAS", 1, "LOTEBUSQUEDA");
        var segunda = consultar("MIXTO", "TODAS", 2, "lotebusqueda");
        assertEquals(12, primera.path("total").asInt());
        assertEquals(2, primera.path("totalPaginas").asInt());
        assertEquals(10, primera.path("items").size());
        assertEquals(2, segunda.path("items").size());
        assertEquals(asociaciones.getLast().longValue(), primera.path("items").get(0).path("asociacionId").asLong());
        assertEquals(asociaciones.get(1).longValue(), segunda.path("items").get(0).path("asociacionId").asLong());
        assertEquals(asociaciones.getFirst().longValue(), segunda.path("items").get(1).path("asociacionId").asLong());

        HttpResponse<String> repetida = dueno.get(
                "/api/v1/tarjetas-rfid?tipoEntidad=MIXTO&busqueda=uno&busqueda=dos");
        assertEquals(400, repetida.statusCode());
        String larga = "X".repeat(101);
        HttpResponse<String> invalida = dueno.get("/api/v1/tarjetas-rfid?tipoEntidad=MIXTO&busqueda=" + larga);
        assertEquals(400, invalida.statusCode());
        assertFalse(invalida.body().contains(larga));
        assertFalse(salida.getAll().contains(uidCliente));
        assertFalse(salida.getAll().contains("BUSCARCLIENTE"));
    }

    private JsonNode consultar(String tipo, String estado, int pagina, String busqueda)
            throws Exception {
        String termino = URLEncoder.encode(busqueda, StandardCharsets.UTF_8);
        HttpResponse<String> respuesta = dueno.get("/api/v1/tarjetas-rfid?tipoEntidad=" + tipo
                + "&estado=" + estado + "&pagina=" + pagina + "&busqueda=" + termino);
        assertEquals(200, respuesta.statusCode());
        assertTrue(respuesta.headers().firstValue("cache-control").orElse("").contains("no-store"));
        return json(respuesta);
    }

    private void asociarCliente(String uid, UUID clienteId) {
        jdbc.update("INSERT INTO asociacion_tarjeta_rfid1(uid_canonico, cliente_id, asociada_en) VALUES (?, ?, ?)",
                uid, clienteId, INSTANTE);
    }

    private long asociarEmpleado(String uid, long empleadoId) {
        return jdbc.queryForObject("INSERT INTO asociacion_tarjeta_rfid1(uid_canonico, empleado_id, asociada_en) "
                + "VALUES (?, ?, ?) RETURNING asociacion_id", Long.class, uid, empleadoId, INSTANTE);
    }
}
