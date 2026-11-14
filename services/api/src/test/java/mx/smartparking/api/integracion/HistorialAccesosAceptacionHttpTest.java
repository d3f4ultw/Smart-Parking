package mx.smartparking.api.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

/** Aceptación HTTP contra PostgreSQL 18.6 desechable con las migraciones vigentes. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class HistorialAccesosAceptacionHttpTest extends HistorialAccesosAceptacionHttpSoporte {

    @DynamicPropertySource
    static void configurarPostgresDesechable(DynamicPropertyRegistry registro) {
        if (!"true".equalsIgnoreCase(System.getenv("SMARTPARKING_POSTGRES_DESCARTABLE"))) {
            throw new IllegalStateException("El test requiere SMARTPARKING_POSTGRES_DESCARTABLE=true.");
        }
        String host = variable("POSTGRES_HOST");
        String port = variable("POSTGRES_PORT");
        String db = variable("POSTGRES_DB");
        registro.add("spring.datasource.url", () -> "jdbc:postgresql://" + host + ":" + port + "/" + db);
        registro.add("spring.datasource.username", () -> variable("POSTGRES_USER"));
        registro.add("spring.datasource.password", () -> variable("POSTGRES_PASSWORD"));
        registro.add("smartparking.rfid1.token-sha256", () -> sha256(TOKEN_DISPOSITIVO));
        registro.add("spring.mail.host", () -> "127.0.0.1");
        registro.add("spring.mail.port", () -> 1);
        registro.add("spring.mail.properties.mail.smtp.connectiontimeout", () -> "500");
        registro.add("spring.mail.properties.mail.smtp.timeout", () -> "500");
        registro.add("spring.mail.properties.mail.smtp.writetimeout", () -> "500");
    }

    @Test
    void verificaAutorizacionHistorialPaginacionZonaSseReintentosYRollback() throws Exception {
        assertEquals(401, get("/api/v1/accesos/historial", null).getStatusCode().value());
        Sesion dueno = iniciarDueno();
        ResponseEntity<Map<String, Object>> historialInicial = get("/api/v1/accesos/historial", dueno);
        Map<String, Object> errorInicial = historialInicial.getBody();
        String diagnostico = errorInicial == null ? "sin cuerpo"
                : "codigo=" + errorInicial.get("codigo") + ", mensaje="
                        + errorInicial.getOrDefault("mensaje", errorInicial.get("error"));
        assertEquals(200, historialInicial.getStatusCode().value(), diagnostico);
        assertEquals("no-store, private", historialInicial.getHeaders().getFirst(HttpHeaders.CACHE_CONTROL));
        Sesion cliente = registrarEIniciarCliente();
        assertEquals(403, get("/api/v1/accesos/historial", cliente).getStatusCode().value());
        assertEquals(401, intentarLoginOperador().getStatusCode().value());
        assertEquals(401, getConBearer("/api/v1/accesos/historial").getStatusCode().value());

        String uidCliente = uid();
        String uidEmpleado = uid();
        String uidCancelado = uid();
        long empleadoId = crearEmpleado("Emilia", "Prueba");
        long asociacionEmpleado = asociar(uidEmpleado, empleadoId);
        long empleadoCancelado = crearEmpleado("Cancelado", "Prueba");
        String uidCanceladoActual = asociarYCancelar(uidCancelado, empleadoCancelado);
        UUID idCliente = clienteId();
        prepararMembresiaVigente(idCliente);
        prepararCapacidadDisponible(10);
        long asociacionCliente = asociarCliente(uidCliente, idCliente);
        String lecturaEntrada = UUID.randomUUID().toString();
        String lecturaPendiente = UUID.randomUUID().toString();
        String lecturaSalida = UUID.randomUUID().toString();
        assertDecision("RFID2", uidCliente, lecturaEntrada, "AUTORIZADA", null);
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM evento_acceso evento
                JOIN movimiento_estacionamiento movimiento USING (movimiento_id)
                WHERE evento.lector='RFID2' AND evento.lectura_id=? AND movimiento.lectura_id=?
                    AND evento.ocurrido_en=movimiento.instante_entrada
                """, Integer.class, UUID.fromString(lecturaEntrada), UUID.fromString(lecturaEntrada)));
        assertDecision("RFID2", uidCliente, lecturaPendiente, "DENEGADA", "ENTRADA_PENDIENTE");
        assertEquals(1, contarMovimientos(uidCliente));
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM evento_acceso WHERE lector='RFID2' "
                + "AND lectura_id=? AND movimiento_id IS NOT NULL", Integer.class,
                UUID.fromString(lecturaPendiente)));
        long idPendiente = idEvento("RFID2", lecturaPendiente);
        Instant horaPendiente = horaEvento("RFID2", lecturaPendiente);
        Thread.sleep(2);
        assertDecision("RFID3", uidCliente, lecturaSalida, "AUTORIZADA", null);
        assertDecision("RFID3", uidCliente, lecturaSalida, "AUTORIZADA", null);
        assertEquals(1, contarEvento("RFID3", lecturaSalida));
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM evento_acceso evento
                JOIN movimiento_estacionamiento movimiento USING (movimiento_id)
                WHERE evento.lector='RFID3' AND evento.lectura_id=? AND movimiento.lectura_id=?
                    AND evento.ocurrido_en=movimiento.instante_salida
                """, Integer.class, UUID.fromString(lecturaSalida), UUID.fromString(lecturaEntrada)));
        Instant salidaConfirmada = jdbc.queryForObject("SELECT instante_salida FROM movimiento_estacionamiento "
                + "WHERE lectura_id=?", java.time.OffsetDateTime.class, UUID.fromString(lecturaEntrada)).toInstant();
        String lecturaSinEntrada = UUID.randomUUID().toString();
        assertDecision("RFID3", uidCliente, lecturaSinEntrada, "DENEGADA", "SIN_ENTRADA_ABIERTA");
        assertEquals(salidaConfirmada, jdbc.queryForObject("SELECT instante_salida FROM movimiento_estacionamiento "
                + "WHERE lectura_id=?", java.time.OffsetDateTime.class, UUID.fromString(lecturaEntrada)).toInstant());
        assertEquals(UUID.fromString(lecturaSalida), jdbc.queryForObject("SELECT lectura_salida_id FROM "
                + "movimiento_estacionamiento WHERE lectura_id=?", UUID.class, UUID.fromString(lecturaEntrada)));
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM evento_acceso WHERE lector='RFID3' "
                + "AND lectura_id=? AND movimiento_id IS NOT NULL", Integer.class,
                UUID.fromString(lecturaSinEntrada)));
        assertEquals(1, contarMovimientos(uidCliente));
        assertDecision("RFID2", uidCliente, lecturaPendiente, "AUTORIZADA", null);
        assertEquals(idPendiente, idEvento("RFID2", lecturaPendiente));
        assertTrue(horaEvento("RFID2", lecturaPendiente).isAfter(horaPendiente));
        assertEquals(1, contarEvento("RFID2", lecturaPendiente));
        assertEquals(2, contarMovimientos(uidCliente));

        String legacyId = UUID.randomUUID().toString();
        insertarMovimientoPrevioV15(uidEmpleado, asociacionEmpleado, empleadoId, legacyId);
        assertDecision("RFID2", uidEmpleado, legacyId, "AUTORIZADA", null);
        assertEquals(0, contarEvento("RFID2", legacyId));
        assertEquals(409, enviarDecision("RFID2", uidEmpleado, lecturaEntrada).getStatusCode().value());
        assertEquals(1, contarEvento("RFID2", lecturaEntrada));

        String uidMismoUuid = uid();
        long empleadoMismoUuid = crearEmpleado("Mismo", "UUID");
        asociar(uidMismoUuid, empleadoMismoUuid);
        String lecturaMismoUuid = UUID.randomUUID().toString();
        assertDecision("RFID2", uidMismoUuid, lecturaMismoUuid, "AUTORIZADA", null);
        assertDecision("RFID3", uidMismoUuid, lecturaMismoUuid, "AUTORIZADA", null);
        assertEquals(1, contarEvento("RFID2", lecturaMismoUuid));
        assertEquals(1, contarEvento("RFID3", lecturaMismoUuid));

        String uidDesconocido = uid();
        String lecturaDesconocida = UUID.randomUUID().toString();
        try (SseProbe sse = abrirSse(dueno)) {
            assertDecision("RFID2", uidDesconocido, lecturaDesconocida, "DENEGADA", "TARJETA_DESCONOCIDA");
            String evento = sse.esperar("acceso.historial.actualizado", Duration.ofSeconds(3));
            assertNotNull(evento);
            assertTrue(evento.endsWith("\n{}"), "El payload SSE debe ser exactamente un objeto vacío.");
            assertFalse(evento.contains(uidDesconocido));
            assertFalse(evento.contains(lecturaDesconocida));
            assertNull(jdbc.queryForObject("SELECT asociacion_id FROM evento_acceso WHERE lector='RFID2' "
                    + "AND lectura_id=?", Long.class, UUID.fromString(lecturaDesconocida)));
            Instant horaDenegacion = horaEvento("RFID2", lecturaDesconocida);
            assertDecision("RFID2", uidDesconocido, lecturaDesconocida, "DENEGADA", "TARJETA_DESCONOCIDA");
            assertEquals(horaDenegacion, horaEvento("RFID2", lecturaDesconocida));
            assertNull(sse.esperar("acceso.historial.actualizado", Duration.ofMillis(300)));
            assertEquals(1, contarEvento("RFID2", lecturaDesconocida));
        }

        String lecturaDesconocida3 = UUID.randomUUID().toString();
        assertDecision("RFID3", uid(), lecturaDesconocida3, "DENEGADA", "TARJETA_DESCONOCIDA");
        assertNull(jdbc.queryForObject("SELECT asociacion_id FROM evento_acceso WHERE lector='RFID3' AND lectura_id=?",
                Long.class, UUID.fromString(lecturaDesconocida3)));

        String lecturaCancelada2 = UUID.randomUUID().toString();
        String lecturaCancelada3 = UUID.randomUUID().toString();
        assertDecision("RFID2", uidCanceladoActual, lecturaCancelada2, "DENEGADA", "TARJETA_CANCELADA");
        assertDecision("RFID3", uidCanceladoActual, lecturaCancelada3, "DENEGADA", "TARJETA_CANCELADA");
        assertEquals(1, contarEvento("RFID2", lecturaCancelada2));
        assertEquals(1, contarEvento("RFID3", lecturaCancelada3));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM evento_acceso WHERE lector='RFID2' "
                + "AND lectura_id=? AND asociacion_id IS NOT NULL", Integer.class, UUID.fromString(lecturaCancelada2)));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM evento_acceso WHERE lector='RFID3' "
                + "AND lectura_id=? AND asociacion_id IS NOT NULL", Integer.class, UUID.fromString(lecturaCancelada3)));

        validarHistorial(dueno, asociacionEmpleado);
        validarFalloPersistenciaRevierte(dueno, uid(), crearEmpleado("Fallo", "Prueba"));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM asociacion_tarjeta_rfid1 WHERE asociacion_id = ?",
                Integer.class, asociacionCliente));
    }

    private void validarHistorial(Sesion dueno, long asociacionEmpleado) {
        insertarEventosPaginables(asociacionEmpleado);
        ResponseEntity<Map<String, Object>> pagina = get("/api/v1/accesos/historial?periodo=TODO", dueno);
        assertEquals(200, pagina.getStatusCode().value());
        Map<String, Object> cuerpo = Objects.requireNonNull(pagina.getBody());
        List<Map<String, Object>> items = items(cuerpo);
        assertEquals(10, items.size());
        assertTrue(((Number) cuerpo.get("totalRegistros")).longValue() >= 55);
        assertEquals(Boolean.TRUE, cuerpo.get("haySiguiente"));
        assertEquals("America/New_York", cuerpo.get("zonaHoraria"));
        assertEquals("1", String.valueOf(cuerpo.get("pagina")));
        for (int indice = 1; indice < items.size(); indice++) {
            Map<String, Object> anterior = items.get(indice - 1);
            Map<String, Object> actual = items.get(indice);
            Instant instanteAnterior = Instant.parse((String) anterior.get("ocurridoEn"));
            Instant instanteActual = Instant.parse((String) actual.get("ocurridoEn"));
            assertFalse(instanteAnterior.isBefore(instanteActual), "El historial debe ir en orden descendente.");
            if (instanteAnterior.equals(instanteActual)) {
                assertTrue(((Number) anterior.get("id")).longValue() > ((Number) actual.get("id")).longValue(),
                        "Los eventos con la misma fecha se ordenan por ID descendente.");
            }
        }
        Instant instante = Instant.parse((String) items.getFirst().get("ocurridoEn"));
        assertEquals(FORMATO_LOCAL.format(instante.atZone(ZoneId.of("America/New_York"))),
                items.getFirst().get("ocurridoEnLocal"));
        assertTrue(pagina.getHeaders().getFirst(HttpHeaders.VARY).contains("Cookie"));
        assertFalse(items.stream().anyMatch(item -> item.containsKey("uid") || item.containsKey("lecturaId")));
        assertTrue(items.stream().anyMatch(item -> item.get("persona") instanceof Map<?, ?> persona
                && "EMPLEADO".equals(persona.get("tipo")) && "Emilia Prueba".equals(persona.get("nombre"))));

        ResponseEntity<Map<String, Object>> segunda = get("/api/v1/accesos/historial?pagina=2&periodo=TODO", dueno);
        assertEquals(200, segunda.getStatusCode().value());
        assertEquals("2", String.valueOf(segunda.getBody().get("pagina")));
        List<Map<String, Object>> itemsSegunda = items(segunda.getBody());
        assertFalse(itemsSegunda.isEmpty());
        assertEquals(10, itemsSegunda.size());
        ResponseEntity<Map<String, Object>> personalizada = get("/api/v1/accesos/historial?periodo=PERSONALIZADO"
                + "&desde=2050-01-01&hasta=2050-01-01", dueno);
        assertEquals(200, personalizada.getStatusCode().value());
        assertEquals(55L, ((Number) personalizada.getBody().get("totalRegistros")).longValue(),
                "El rango incluye el día local completo y excluye los días vecinos.");
        assertEquals(10, items(personalizada.getBody()).size());
        ResponseEntity<Map<String, Object>> respuestaUltimaPagina = get("/api/v1/accesos/historial?pagina=6"
                + "&periodo=PERSONALIZADO&desde=2050-01-01&hasta=2050-01-01", dueno);
        List<Map<String, Object>> ultimaPagina = items(respuestaUltimaPagina.getBody());
        assertEquals(5, ultimaPagina.size());
        assertEquals(Boolean.FALSE, respuestaUltimaPagina.getBody().get("haySiguiente"));
        for (int indice = 1; indice < ultimaPagina.size(); indice++) {
            assertTrue(((Number) ultimaPagina.get(indice - 1).get("id")).longValue()
                    > ((Number) ultimaPagina.get(indice).get("id")).longValue());
        }
        ResponseEntity<Map<String, Object>> cambioHorario = get("/api/v1/accesos/historial?periodo=PERSONALIZADO"
                + "&desde=2026-11-01&hasta=2026-11-01", dueno);
        assertEquals(3L, ((Number) cambioHorario.getBody().get("totalRegistros")).longValue(),
                "El día local incluye su inicio, ambas horas repetidas y excluye la medianoche siguiente.");
        List<Map<String, Object>> eventosCambioHorario = items(cambioHorario.getBody());
        assertTrue(eventosCambioHorario.stream().anyMatch(item ->
                "2026-11-01T01:30:00-04:00".equals(item.get("ocurridoEnLocal"))));
        assertTrue(eventosCambioHorario.stream().anyMatch(item ->
                "2026-11-01T01:30:00-05:00".equals(item.get("ocurridoEnLocal"))));
        ResponseEntity<Map<String, Object>> filtrada = get("/api/v1/accesos/historial?lector=RFID3"
                + "&resultado=DENEGADA&periodo=PERSONALIZADO&desde=2050-01-01&hasta=2050-01-01", dueno);
        assertTrue(items(filtrada.getBody()).stream().allMatch(item ->
                "RFID3".equals(item.get("lector")) && "DENEGADA".equals(item.get("resultado"))));
        assertEquals(27L, ((Number) filtrada.getBody().get("totalRegistros")).longValue());
        assertEquals(400, get("/api/v1/accesos/historial?pagina=0", dueno).getStatusCode().value());
        assertEquals(400, get("/api/v1/accesos/historial?lector=RFID1", dueno).getStatusCode().value());
        assertEquals(400, get("/api/v1/accesos/historial?resultado=ERROR", dueno).getStatusCode().value());
        assertEquals(400, get("/api/v1/accesos/historial?periodo=PERSONALIZADO&desde=2050-02-29"
                + "&hasta=2050-03-01", dueno).getStatusCode().value());
        assertEquals(400, get("/api/v1/accesos/historial?periodo=PERSONALIZADO&desde=2050-01-02"
                + "&hasta=2050-01-01", dueno).getStatusCode().value());
    }

    private void validarFalloPersistenciaRevierte(Sesion dueno, String uid, long empleadoId) throws Exception {
        asociar(uid, empleadoId);
        String tarjeta = uid;
        String entrada = UUID.randomUUID().toString();
        try (SseProbe sse = abrirSse(dueno)) {
            activarFalloEvento();
            try {
                ResponseEntity<Map<String, Object>> respuesta = enviarDecision("RFID2", tarjeta, entrada);
                assertEquals(503, respuesta.getStatusCode().value());
                assertFalse(String.valueOf(respuesta.getBody()).contains(tarjeta));
                assertEquals(0, contarMovimientoLectura(entrada));
                assertEquals(0, contarEvento("RFID2", entrada));
                assertNull(sse.esperar("acceso.historial.actualizado", Duration.ofMillis(250)));
                String desconocida = uid();
                String lecturaDenegada = UUID.randomUUID().toString();
                ResponseEntity<Map<String, Object>> rechazo = enviarDecision("RFID2", desconocida, lecturaDenegada);
                assertEquals(503, rechazo.getStatusCode().value());
                assertFalse(String.valueOf(rechazo.getBody()).contains(desconocida));
                assertEquals(0, contarEvento("RFID2", lecturaDenegada));
                assertNull(sse.esperar("acceso.historial.actualizado", Duration.ofMillis(250)));
            } finally {
                desactivarFalloEvento();
            }
            String entradaAbierta = UUID.randomUUID().toString();
            assertDecision("RFID2", tarjeta, entradaAbierta, "AUTORIZADA", null);
            assertNotNull(sse.esperar("acceso.historial.actualizado", Duration.ofSeconds(3)));
            String salida = UUID.randomUUID().toString();
            activarFalloEvento();
            try {
                ResponseEntity<Map<String, Object>> respuesta = enviarDecision("RFID3", tarjeta, salida);
                assertEquals(503, respuesta.getStatusCode().value());
                assertEquals(0, contarEvento("RFID3", salida));
                assertEquals(1, jdbc.queryForObject("""
                        SELECT count(*) FROM movimiento_estacionamiento
                        WHERE lectura_id = ? AND instante_salida IS NULL
                        """, Integer.class, UUID.fromString(entradaAbierta)));
                assertNull(sse.esperar("acceso.historial.actualizado", Duration.ofMillis(250)));
            } finally {
                desactivarFalloEvento();
            }
        }
    }

}
