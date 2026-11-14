package mx.smartparking.api.rfid1.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.UUID;
import java.net.http.HttpResponse;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import tools.jackson.databind.JsonNode;

/** Conserva el contrato HTTP Stage 2 bajo la confirmación explícita añadida en Stage 1. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@EnabledIfSystemProperty(named = "smartparking.integration.disposable", matches = "true")
@ExtendWith(OutputCaptureExtension.class)
class CapturasRfid1ApiAceptacionTest extends TarjetasRfid1Stage1TestSupport {

    @Test
    void lecturaTecnicaConservaLaCapturaSinAsociarHastaConfirmacion(CapturedOutput salida) throws Exception {
        Persona empleado = crearEmpleado("rfid-stage2-compatibilidad");
        Captura captura = crearCaptura(dueno, empleado.tipoEntidad, empleado.codigo);
        iniciarCaptura(captura.id);
        String uid = "B5B6B7B8";

        Resultado lectura = leer(captura.id, uid, "5A01");
        assertEquals(200, lectura.estado);
        assertEquals("VISTA_PREVIA", lectura.cuerpo.path("estado").asText());
        assertEquals("PREVIEW_READY", lectura.cuerpo.path("resultado").asText());
        assertFalse(lectura.texto.contains(uid));
        assertEquals(0, contarAsociacionesPorPersona("EMPLEADO", empleado.id));
        assertEquals(1, contarUidTemporal(captura.id));

        HttpResponse<String> capturaPrivada = dueno.get("/api/v1/rfid-1/capturas/" + captura.id);
        assertEquals(200, capturaPrivada.statusCode());
        assertFalse(capturaPrivada.body().contains(uid));
        HttpResponse<String> previa = dueno.get("/api/v1/rfid-1/capturas/" + captura.id + "/vista-previa");
        assertEquals(200, previa.statusCode());
        JsonNode vistaJson = json(previa);
        assertTrue(vistaJson.has("uid"), "La vista previa debe usar el campo de contrato uid.");
        assertTrue(uid.equals(vistaJson.path("uid").asText()),
                "La vista previa de compatibilidad debe coincidir con la lectura sintética.");

        HttpResponse<String> confirmacion = dueno.confirmar(captura.id, UUID.randomUUID().toString());
        assertEquals(200, confirmacion.statusCode());
        assertEquals("COMPLETADA", estadoCaptura(captura.id));
        assertEquals(1, contarAsociacionesPorPersona("EMPLEADO", empleado.id));
        assertEquals(0, contarUidTemporal(captura.id));
        assertFalse(salida.getAll().contains(uid));
        assertFalse(salida.getAll().contains(TOKEN_DISPOSITIVO));
        assertTrue(jdbc.queryForObject(
                "SELECT count(*) FROM flyway_schema_history WHERE version='12' AND success", Integer.class) == 1);
    }
}
