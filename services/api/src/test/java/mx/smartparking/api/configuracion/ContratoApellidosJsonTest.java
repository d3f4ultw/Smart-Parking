package mx.smartparking.api.configuracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

class ContratoApellidosJsonTest {

    private final JsonMapper json = new JsonMapper();

    @Test
    void deserializaCamposCanonicosYPermiteOmitirElSegundoApellido() throws Exception {
        SolicitudConfiguracion solicitud = json.readValue(solicitudJson(
                "\"primerApellido\":\"López\","), SolicitudConfiguracion.class);
        SolicitudConfiguracion solicitudConSegundoNulo = json.readValue(solicitudJson(
                "\"primerApellido\":\"López\",\n                    \"segundoApellido\":null,"),
                SolicitudConfiguracion.class);

        DatosPropietario propietario = solicitud.validar().propietario();
        assertEquals("López", propietario.primerApellido());
        assertNull(propietario.segundoApellido());
        assertNull(solicitudConSegundoNulo.validar().propietario().segundoApellido());
    }

    @Test
    void aceptaNombresJsonAnterioresComoAliasDeEntrada() throws Exception {
        SolicitudConfiguracion solicitud = json.readValue(solicitudJson(
                "\"apellidoPaterno\":\"López\",\n                    \"apellidoMaterno\":\"García\","),
                SolicitudConfiguracion.class);

        DatosPropietario propietario = solicitud.validar().propietario();
        assertEquals("López", propietario.primerApellido());
        assertEquals("García", propietario.segundoApellido());
    }

    @Test
    void rechazaElPrimerApellidoOmitido() throws Exception {
        SolicitudConfiguracion solicitud = json.readValue(solicitudJson(""), SolicitudConfiguracion.class);

        assertThrows(IllegalArgumentException.class, solicitud::validar);
    }

    @Test
    void serializaNombresCanonicosYConservaLosAliasDeSalida() throws Exception {
        PanelPropietario.PropietarioPanel propietario = new PanelPropietario.PropietarioPanel(
                "Ana", "López", null, "ana@example.test");
        JsonNode respuesta = json.readTree(json.writeValueAsString(propietario));

        assertEquals("López", respuesta.path("primerApellido").asText());
        assertEquals("López", respuesta.path("apellidoPaterno").asText());
        assertTrue(respuesta.has("segundoApellido"));
        assertTrue(respuesta.get("segundoApellido").isNull());
        assertTrue(respuesta.has("apellidoMaterno"));
        assertTrue(respuesta.get("apellidoMaterno").isNull());
    }

    private static String solicitudJson(String camposApellidos) {
        return """
                {
                  "propietario": {
                    "nombres": "Ana",
                    %s
                    "correo": "ana@example.test",
                    "contrasenaAcceso": "acceso-seguro-2026",
                    "contrasenaAdministrativa": "admin-seguro-2026"
                  },
                  "estacionamiento": {
                    "nombre": "Centro",
                    "tipo": "PUBLICO",
                    "horario": {
                      "modo": "INTERVALO_DIARIO",
                      "zonaHoraria": "UTC",
                      "horaApertura": "09:00",
                      "horaCierre": "17:00"
                    }
                  }
                }
                """.formatted(camposApellidos);
    }
}
