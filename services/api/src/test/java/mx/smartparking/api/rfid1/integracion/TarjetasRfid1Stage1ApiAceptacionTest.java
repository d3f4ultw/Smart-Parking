package mx.smartparking.api.rfid1.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.net.http.HttpResponse;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.junit.jupiter.api.extension.ExtendWith;
import tools.jackson.databind.JsonNode;

@ExtendWith(OutputCaptureExtension.class)
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@EnabledIfSystemProperty(named = "smartparking.integration.disposable", matches = "true")
class TarjetasRfid1Stage1ApiAceptacionTest extends TarjetasRfid1Stage1TestSupport {
    private static final String PRICE_ID = "price_1USQ5HAqtHmR2qmyAWwUp5vy";

    @Test
    void clienteRequiereConfirmacionExplicitaYReplaySeguro(CapturedOutput salida) throws Exception {
        Persona persona = crearCliente("rfid-stage1-cliente");
        insertarMembresiaActiva(persona.clienteId);
        Captura captura = crearCaptura(dueno, "CLIENTE", persona.codigo);
        iniciarCaptura(captura.id);
        String uid = "A1B2C3D4";

        Resultado lectura = leer(captura.id, uid, "0006");
        assertEquals(200, lectura.estado);
        assertEquals("VISTA_PREVIA", lectura.cuerpo.path("estado").asText());
        assertEquals("PREVIEW_READY", lectura.cuerpo.path("resultado").asText());
        assertFalse(lectura.texto.contains(uid));
        assertFalse(lectura.texto.contains(TOKEN_DISPOSITIVO));
        assertEquals(0, contarAsociacionesPorUid(uid));
        assertEquals(1, contarUidTemporal(captura.id));

        HttpResponse<String> resumen = dueno.get("/api/v1/rfid-1/capturas/" + captura.id);
        assertEquals(200, resumen.statusCode());
        assertFalse(resumen.body().contains(uid));
        assertFalse(resumen.body().contains(TOKEN_DISPOSITIVO));

        HttpResponse<String> vista = dueno.get("/api/v1/rfid-1/capturas/" + captura.id + "/vista-previa");
        assertEquals(200, vista.statusCode());
        JsonNode vistaJson = json(vista);
        assertTrue(vistaJson.has("uid"), "La vista previa debe usar el campo de contrato uid.");
        assertTrue(uid.equals(vistaJson.path("uid").asText()),
                "La vista previa autorizada debe coincidir con la lectura sintética.");
        assertTrue(vista.headers().firstValue("Cache-Control").orElse("").contains("no-store"));
        assertTrue(vista.headers().firstValue("Vary").orElse("").toLowerCase().contains("cookie"));
        Instant vistaEn = Instant.parse(json(vista).path("previsualizadaEn").asText());
        Instant venceEn = Instant.parse(json(vista).path("confirmacionVenceEn").asText());
        assertEquals(Duration.ofSeconds(300), Duration.between(vistaEn, venceEn));
        HttpResponse<String> estadoDispositivo = dispositivo.get("/api/v1/dispositivos/rfid-1/capturas/activa");
        assertEquals(200, estadoDispositivo.statusCode());
        assertFalse(estadoDispositivo.body().contains(uid));
        assertFalse(estadoDispositivo.body().contains(TOKEN_DISPOSITIVO));

        Api otraSesion = nuevaSesionDueno();
        // La vista previa sigue ocupando el único RFID1, incluso para otro intento del mismo objetivo.
        HttpResponse<String> segundaCaptura = otraSesion.post("/api/v1/rfid-1/capturas",
                java.util.Map.of("tipoEntidad", persona.tipoEntidad, "codigoPersona", persona.codigo),
                java.util.Map.of(CSRF, otraSesion.csrf(), "Idempotency-Key", UUID.randomUUID().toString()));
        assertEquals(409, segundaCaptura.statusCode());
        assertFalse(segundaCaptura.body().contains(uid));
        assertFalse(segundaCaptura.body().contains(TOKEN_DISPOSITIVO));
        assertEquals(1, jdbc.queryForObject(
                "SELECT count(*) FROM captura_rfid1 WHERE estado IN ('PENDIENTE','ESCANEANDO','VISTA_PREVIA')",
                Integer.class));
        assertTrue(otraSesion.get("/api/v1/rfid-1/capturas/" + captura.id + "/vista-previa").statusCode() >= 400);
        assertTrue(anonimo.get("/api/v1/tarjetas-rfid/personas?tipoEntidad=CLIENTE").statusCode() >= 400);
        assertTrue(dispositivo.get("/api/v1/tarjetas-rfid/personas?tipoEntidad=CLIENTE").statusCode() >= 400);

        String clave = UUID.randomUUID().toString();
        assertEquals(403, dueno.postSinCsrf("/api/v1/rfid-1/capturas/" + captura.id + "/confirmacion",
                "{\"claveConfirmacion\":\"" + clave + "\"}").statusCode());
        assertEquals(1, contarUidTemporal(captura.id));
        assertEquals(0, contarAsociacionesPorUid(uid));

        // La primera respuesta se descarta a propósito: el cliente puede repetir la misma clave.
        dueno.confirmar(captura.id, clave);
        long idPersistido = jdbc.queryForObject(
                "SELECT asociacion_id FROM asociacion_tarjeta_rfid1 WHERE uid_canonico=?", Long.class, uid);
        HttpResponse<String> repeticion = dueno.confirmar(captura.id, clave);
        assertEquals(200, repeticion.statusCode());
        assertEquals(idPersistido, json(repeticion).path("asociacionId").asLong());
        assertEquals(1, contarAsociacionesPorUid(uid));
        assertEquals(0, contarUidTemporal(captura.id));
        assertEquals("COMPLETADA", estadoCaptura(captura.id));

        HttpResponse<String> claveDistinta = dueno.confirmar(captura.id, UUID.randomUUID().toString());
        assertEquals(409, claveDistinta.statusCode());
        assertEquals(1, contarAsociacionesPorUid(uid));
        HttpResponse<String> directorio = dueno.get("/api/v1/tarjetas-rfid?tipoEntidad=CLIENTE&estado=ACTIVA&pagina=1");
        assertEquals(200, directorio.statusCode());
        assertTrue(json(directorio).findValues("uid").stream().anyMatch(valor -> uid.equals(valor.asText())),
                "El directorio DUENO debe incluir el UID de la tarjeta.");
        long idTarjeta = jdbc.queryForObject(
                "SELECT asociacion_id FROM asociacion_tarjeta_rfid1 WHERE uid_canonico=?", Long.class, uid);
        HttpResponse<String> detalle = dueno.get("/api/v1/tarjetas-rfid/" + idTarjeta);
        assertEquals(200, detalle.statusCode());
        assertTrue(uid.equals(json(detalle).path("uid").asText()),
                "El detalle DUENO debe incluir el UID de la tarjeta.");
        assertFalse(directorio.body().contains(TOKEN_DISPOSITIVO));
        assertFalse(salida.getAll().contains(TOKEN_DISPOSITIVO));
        assertFalse(salida.getAll().contains(uid));
    }

    @Test
    void empleadoUsaMismasReglasYUidHistoricoNoFinalizaCaptura(CapturedOutput salida) throws Exception {
        Persona cliente = crearCliente("rfid-stage1-origen");
        insertarMembresiaActiva(cliente.clienteId);
        asociar(dueno, cliente, "B1B2B3B4");
        Persona empleado = crearEmpleado("rfid-stage1-empleado");
        Captura captura = crearCaptura(dueno, "EMPLEADO", empleado.codigo);
        iniciarCaptura(captura.id);

        Resultado duplicada = leer(captura.id, "B1B2B3B4", "0001");
        assertEquals(409, duplicada.estado);
        assertEquals("TARJETA_YA_REGISTRADA", duplicada.cuerpo.path("codigo").asText());
        assertFalse(duplicada.texto.contains("B1B2B3B4"));
        assertEquals("ESCANEANDO", estadoCaptura(captura.id));
        assertEquals(0, contarUidTemporal(captura.id));
        assertEquals(0, contarAsociacionesPorPersona("EMPLEADO", empleado.id));

        String uid = "11223344";
        Resultado lectura = leer(captura.id, uid, "0002");
        assertEquals(200, lectura.estado);
        assertEquals("VISTA_PREVIA", lectura.cuerpo.path("estado").asText());
        assertFalse(lectura.texto.contains(uid));
        assertEquals(0, contarAsociacionesPorPersona("EMPLEADO", empleado.id));
        assertEquals(1, contarUidTemporal(captura.id));
        HttpResponse<String> vista = dueno.get("/api/v1/rfid-1/capturas/" + captura.id + "/vista-previa");
        assertEquals(200, vista.statusCode());
        JsonNode vistaJson = json(vista);
        assertTrue(vistaJson.has("uid"), "La vista previa debe usar el campo de contrato uid.");
        assertTrue(uid.equals(vistaJson.path("uid").asText()),
                "La vista previa autorizada debe pertenecer a la lectura actual.");

        HttpResponse<String> confirmada = dueno.confirmar(captura.id, UUID.randomUUID().toString());
        assertEquals(200, confirmada.statusCode());
        assertEquals(1, contarAsociacionesPorPersona("EMPLEADO", empleado.id));
        assertEquals(0, contarUidTemporal(captura.id));
        assertFalse(salida.getAll().contains(TOKEN_DISPOSITIVO));
        assertFalse(salida.getAll().contains(uid));
    }

    @Test
    void clienteSinMembresiaPermaneceEnBusquedaPeroLaApiRechazaLaCaptura() throws Exception {
        Persona persona = crearCliente("rfid-stage1-sin-membresia");

        HttpResponse<String> respuestaBusqueda = dueno.get(
                "/api/v1/tarjetas-rfid/personas?tipoEntidad=CLIENTE&busqueda=" + persona.codigo);
        assertEquals(200, respuestaBusqueda.statusCode());
        JsonNode candidato = null;
        for (JsonNode elemento : json(respuestaBusqueda)) {
            if (persona.codigo.equals(elemento.path("codigoPersona").asText())) {
                candidato = elemento;
                break;
            }
        }
        assertNotNull(candidato, "El cliente debe seguir apareciendo en la búsqueda.");
        assertFalse(candidato.path("elegible").asBoolean());
        assertEquals("CLIENTE_SIN_MEMBRESIA", candidato.path("motivoNoElegible").asText());

        HttpResponse<String> rechazo = dueno.post(RUTA_CAPTURAS,
                java.util.Map.of("tipoEntidad", "CLIENTE", "codigoPersona", persona.codigo),
                java.util.Map.of(CSRF, dueno.csrf(), "Idempotency-Key", UUID.randomUUID().toString()));

        assertEquals(409, rechazo.statusCode());
        assertEquals("CLIENTE_SIN_MEMBRESIA", json(rechazo).path("codigo").asText());
        assertTrue(json(rechazo).path("mensaje").asText().contains("sin membresía"));
        assertEquals(0, jdbc.queryForObject(
                "SELECT count(*) FROM captura_rfid1 WHERE cliente_id = ?", Integer.class, persona.clienteId));
        assertEquals(0, jdbc.queryForObject(
                "SELECT count(*) FROM asociacion_tarjeta_rfid1 WHERE cliente_id = ?", Integer.class,
                persona.clienteId));
        assertEquals(0, jdbc.queryForObject(
                "SELECT count(*) FROM suscripcion_cliente WHERE cliente_id = ?", Integer.class, persona.clienteId));
    }

    @Test
    void cancelacionSesionYExpiracionLimpianLaFilaTemporal(CapturedOutput salida) throws Exception {
        Persona cancelada = crearEmpleado("rfid-stage1-cancelacion");
        Captura capturaCancelada = crearCaptura(dueno, "EMPLEADO", cancelada.codigo);
        iniciarCaptura(capturaCancelada.id);
        leer(capturaCancelada.id, "C1C2C3C4", "0003");
        assertEquals(1, contarUidTemporal(capturaCancelada.id));
        assertEquals(403, dueno.delete("/api/v1/rfid-1/capturas/" + capturaCancelada.id, java.util.Map.of())
                .statusCode());
        assertEquals(1, contarUidTemporal(capturaCancelada.id));
        assertEquals(204, dueno.cancelarCaptura(capturaCancelada.id).statusCode());
        assertEquals("CANCELADA", estadoCaptura(capturaCancelada.id));
        assertEquals(0, contarUidTemporal(capturaCancelada.id));
        assertEquals(0, contarAsociacionesPorPersona("EMPLEADO", cancelada.id));

        Persona revocada = crearEmpleado("rfid-stage1-revocacion");
        Api sesion = nuevaSesionDueno();
        Captura capturaRevocada = crearCaptura(sesion, "EMPLEADO", revocada.codigo);
        iniciarCaptura(capturaRevocada.id);
        leer(capturaRevocada.id, "D1D2D3D4", "0004");
        assertEquals(1, contarUidTemporal(capturaRevocada.id));
        assertTrue(sesion.cerrarSesion().statusCode() < 400);
        assertEquals("CANCELADA", estadoCaptura(capturaRevocada.id));
        assertEquals(0, contarUidTemporal(capturaRevocada.id));
        assertEquals(0, contarAsociacionesPorPersona("EMPLEADO", revocada.id));

        Persona expirada = crearEmpleado("rfid-stage1-expiracion");
        Api sesionActiva = nuevaSesionDueno();
        Captura capturaExpirada = crearCaptura(sesionActiva, "EMPLEADO", expirada.codigo);
        iniciarCaptura(capturaExpirada.id);
        leer(capturaExpirada.id, "E1E2D3D4", "0005");
        jdbc.update("UPDATE captura_rfid1 SET previsualizada_en=now()-interval '301 seconds', "
                + "confirmacion_vence_en=now()-interval '1 second' WHERE captura_id=?", capturaExpirada.id);
        assertTrue(esperarEstado(capturaExpirada.id, "EXPIRADA", Duration.ofSeconds(5)));
        assertEquals(0, contarUidTemporal(capturaExpirada.id));
        assertEquals(0, contarAsociacionesPorPersona("EMPLEADO", expirada.id));
        for (String uid : java.util.List.of("C1C2C3C4", "D1D2D3D4", "E1E2D3D4")) {
            assertFalse(salida.getAll().contains(uid));
        }
        assertFalse(salida.getAll().contains(TOKEN_DISPOSITIVO));
    }

    private void insertarMembresiaActiva(UUID clienteId) {
        String customerId = "cus_" + UUID.randomUUID().toString().replace("-", "");
        String subscriptionId = "sub_" + UUID.randomUUID().toString().replace("-", "");
        Timestamp inicio = Timestamp.from(Instant.now());
        Timestamp fin = Timestamp.from(Instant.now().plusSeconds(2_592_000));
        jdbc.update("""
                INSERT INTO cliente_stripe (
                    cliente_id, estado, stripe_customer_id, livemode, creada_en, actualizada_en)
                VALUES (?, 'ASOCIADO', ?, FALSE, ?, ?)
                """, clienteId, customerId, inicio, inicio);
        jdbc.update("""
                INSERT INTO suscripcion_cliente (
                    stripe_subscription_id, cliente_id, stripe_customer_id, price_id,
                    estado_stripe, estado, invoice_id, estado_factura_stripe,
                    periodo_inicio, periodo_fin, cancel_at_period_end, evento_creado_en,
                    actualizada_en, livemode)
                VALUES (?, ?, ?, ?, 'active', 'ACTIVA', NULL, 'paid', ?, ?, FALSE, ?, ?, FALSE)
                """, subscriptionId, clienteId, customerId, PRICE_ID, inicio, fin, inicio, inicio);
    }
}
