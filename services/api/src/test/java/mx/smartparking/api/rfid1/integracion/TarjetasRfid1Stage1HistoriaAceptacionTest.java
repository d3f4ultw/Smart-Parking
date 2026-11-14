package mx.smartparking.api.rfid1.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.net.http.HttpResponse;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DataIntegrityViolationException;

@ExtendWith(OutputCaptureExtension.class)
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@EnabledIfSystemProperty(named = "smartparking.integration.disposable", matches = "true")
class TarjetasRfid1Stage1HistoriaAceptacionTest extends TarjetasRfid1Stage1TestSupport {

    @Test
    void cancelacionConservaHistoricoYLiberaPersonaSinLiberarUid(CapturedOutput salida) throws Exception {
        Persona cliente = crearCliente("rfid-stage1-historial");
        Captura inicial = crearCaptura(dueno, cliente.tipoEntidad, cliente.codigo);
        iniciarCaptura(inicial.id);
        String uidHistorico = "F1F2F3F4";
        assertEquals(200, leer(inicial.id, uidHistorico, "1001").estado);
        assertEquals(200, dueno.confirmar(inicial.id, UUID.randomUUID().toString()).statusCode());
        long asociacionId = idAsociacion(uidHistorico);
        assertThrows(DataAccessException.class,
                () -> jdbc.update("UPDATE asociacion_tarjeta_rfid1 SET uid_canonico='01020304' "
                        + "WHERE asociacion_id=?", asociacionId));
        assertThrows(DataAccessException.class,
                () -> jdbc.update("UPDATE asociacion_tarjeta_rfid1 SET asociada_en=asociada_en+interval '1 second' "
                        + "WHERE asociacion_id=?", asociacionId));

        Persona sinCaptura = crearCliente("rfid-stage1-historial-id");
        jdbc.update("INSERT INTO asociacion_tarjeta_rfid1(uid_canonico,cliente_id) VALUES ('A0A0A0A0',?)",
                sinCaptura.clienteId);
        long idSinCaptura = idAsociacion("A0A0A0A0");
        assertThrows(DataAccessException.class,
                () -> jdbc.update("DELETE FROM asociacion_tarjeta_rfid1 WHERE asociacion_id=?", idSinCaptura));
        assertThrows(DataAccessException.class,
                () -> jdbc.update("UPDATE asociacion_tarjeta_rfid1 SET asociacion_id=asociacion_id+100000 "
                        + "WHERE asociacion_id=?", idSinCaptura));

        String ruta = "/api/v1/tarjetas-rfid/" + asociacionId + "/cancelacion";
        HttpResponse<String> cancelacion = dueno.post(ruta, null, Map.of(CSRF, dueno.csrf()));
        assertEquals(200, cancelacion.statusCode());
        assertEquals(200, dueno.post(ruta, null, Map.of(CSRF, dueno.csrf())).statusCode());
        assertEquals("CANCELADA", estadoAsociacion(asociacionId));
        assertEquals(1, contarAsociacionesPorPersona("CLIENTE", cliente.clienteId));
        Persona otroCliente = crearCliente("rfid-stage1-historial-titular");
        assertThrows(DataAccessException.class,
                () -> jdbc.update("UPDATE asociacion_tarjeta_rfid1 SET cliente_id=? WHERE asociacion_id=?",
                        otroCliente.clienteId, asociacionId));

        HttpResponse<String> detalle = dueno.get("/api/v1/tarjetas-rfid/" + asociacionId);
        assertEquals(200, detalle.statusCode());
        assertTrue(uidHistorico.equals(json(detalle).path("uid").asText()),
                "El detalle DUENO debe conservar el UID de la tarjeta histórica.");
        HttpResponse<String> borrar = dueno.delete("/api/v1/tarjetas-rfid/" + asociacionId, Map.of(CSRF, dueno.csrf()));
        assertTrue(borrar.statusCode() >= 400);

        assertThrows(DataAccessException.class,
                () -> jdbc.update("DELETE FROM asociacion_tarjeta_rfid1 WHERE asociacion_id=?", asociacionId));
        assertThrows(DataAccessException.class,
                () -> jdbc.update("UPDATE asociacion_tarjeta_rfid1 SET estado='ACTIVA', cancelada_en=NULL "
                        + "WHERE asociacion_id=?", asociacionId));
        assertThrows(DataAccessException.class, () -> jdbc.execute("TRUNCATE TABLE asociacion_tarjeta_rfid1"));
        assertThrows(DataAccessException.class,
                () -> jdbc.update("INSERT INTO asociacion_tarjeta_rfid1(uid_canonico,cliente_id) VALUES (?,?)",
                        uidHistorico, cliente.clienteId));

        Captura reemplazo = crearCaptura(dueno, cliente.tipoEntidad, cliente.codigo);
        iniciarCaptura(reemplazo.id);
        Resultado duplicada = leer(reemplazo.id, uidHistorico, "1002");
        assertEquals(409, duplicada.estado);
        assertEquals("TARJETA_YA_REGISTRADA", duplicada.cuerpo.path("codigo").asText());
        assertEquals("ESCANEANDO", estadoCaptura(reemplazo.id));
        assertEquals(0, contarUidTemporal(reemplazo.id));
        String uidNuevo = "F5F6F7F8";
        assertEquals(200, leer(reemplazo.id, uidNuevo, "1003").estado);
        assertEquals(200, dueno.confirmar(reemplazo.id, UUID.randomUUID().toString()).statusCode());
        assertEquals(2, contarAsociacionesPorPersona("CLIENTE", cliente.clienteId));
        assertEquals("CANCELADA", estadoAsociacion(asociacionId));
        assertFalse(salida.getAll().contains(uidHistorico));
        assertFalse(salida.getAll().contains(uidNuevo));
        assertFalse(salida.getAll().contains(TOKEN_DISPOSITIVO));
    }

    @Test
    void rollbackDeConfirmacionYHuellaDeSesionObligatoria(CapturedOutput salida) throws Exception {
        Persona empleado = crearEmpleado("rfid-stage1-rollback");
        Captura captura = crearCaptura(dueno, empleado.tipoEntidad, empleado.codigo);
        iniciarCaptura(captura.id);
        String uid = "A5A6A7A8";
        assertEquals(200, leer(captura.id, uid, "2001").estado);
        long totalAntes = contarAsociacionesPorUid(uid);
        assertThrows(DataIntegrityViolationException.class, () -> jdbc.update(
                "UPDATE uid_temporal_rfid1 SET huella_uid=? WHERE captura_id=?", "0".repeat(64), captura.id));
        assertEquals(1, contarUidTemporal(captura.id));

        String trigger = "uid_temporal_rfid1_forzar_fallo_bd";
        jdbc.execute("CREATE FUNCTION stage1_fallar_borrado_uid() RETURNS trigger LANGUAGE plpgsql AS "
                + "$$ BEGIN RAISE EXCEPTION 'fallo de prueba'; END $$");
        jdbc.execute("CREATE TRIGGER " + trigger + " BEFORE DELETE ON uid_temporal_rfid1 "
                + "FOR EACH ROW EXECUTE FUNCTION stage1_fallar_borrado_uid()");
        String clave = UUID.randomUUID().toString();
        try {
            assertEquals(503, dueno.confirmar(captura.id, clave).statusCode());
            assertEquals(totalAntes, contarAsociacionesPorUid(uid));
            assertEquals("VISTA_PREVIA", estadoCaptura(captura.id));
            assertEquals(1, contarUidTemporal(captura.id));
        } finally {
            jdbc.execute("DROP TRIGGER IF EXISTS " + trigger + " ON uid_temporal_rfid1");
            jdbc.execute("DROP FUNCTION IF EXISTS stage1_fallar_borrado_uid()");
        }

        assertEquals(200, dueno.confirmar(captura.id, clave).statusCode());
        assertEquals(totalAntes + 1, contarAsociacionesPorUid(uid));
        assertEquals(0, contarUidTemporal(captura.id));

        String sesionHash = jdbc.queryForObject(
                "SELECT huella_sesion FROM captura_rfid1 WHERE captura_id=?", String.class, captura.id);
        assertTrue(sesionHash.matches("[0-9a-f]{64}"));
        assertThrows(DataIntegrityViolationException.class,
                () -> jdbc.update("UPDATE captura_rfid1 SET huella_sesion=? WHERE captura_id=?",
                        "0".repeat(64), captura.id));
        String nuevoId = UUID.randomUUID().toString().replace("-", "");
        assertThrows(DataIntegrityViolationException.class, () -> jdbc.update(
                "INSERT INTO captura_rfid1(captura_id,lector,tipo_entidad,codigo_persona,cliente_id,empleado_id,"
                        + "propietario_cuenta_id,revision_acceso,revision_propietario,clave_inicio_hash,"
                        + "huella_solicitud,estado,creada_en,actualizada_en,vence_en,terminada_en) "
                        + "SELECT ?,lector,tipo_entidad,codigo_persona,cliente_id,empleado_id,propietario_cuenta_id,"
                        + "revision_acceso,revision_propietario,?,?,'CANCELADA',now(),now(),"
                        + "now()+interval '120 seconds',now() FROM captura_rfid1 WHERE captura_id=?",
                nuevoId, "a".repeat(64), "b".repeat(64), captura.id));
        assertEquals(0, jdbc.queryForObject(
                "SELECT count(*) FROM captura_rfid1 WHERE captura_id=?", Integer.class, nuevoId));
        assertFalse(salida.getAll().contains(uid));
        assertFalse(salida.getAll().contains(TOKEN_DISPOSITIVO));
    }

    @Test
    void confirmacionRechazadaPorPersonaOcupadaLimpiaUidTemporal(CapturedOutput salida) throws Exception {
        Persona empleado = crearEmpleado("rfid-stage1-confirmacion-persona-ocupada");
        Captura captura = crearCaptura(dueno, empleado.tipoEntidad, empleado.codigo);
        iniciarCaptura(captura.id);
        String uidPrevio = UUID.randomUUID().toString().replace("-", "").substring(0, 20)
                .toUpperCase(java.util.Locale.ROOT);
        String uidCompetidor = UUID.randomUUID().toString().replace("-", "").substring(0, 20)
                .toUpperCase(java.util.Locale.ROOT);
        assertEquals(200, leer(captura.id, uidPrevio, "5001").estado);
        assertEquals(1, contarUidTemporal(captura.id));

        jdbc.update("INSERT INTO asociacion_tarjeta_rfid1(uid_canonico,empleado_id) VALUES (?,?)",
                uidCompetidor, empleado.id);
        HttpResponse<String> rechazo = dueno.confirmar(captura.id, UUID.randomUUID().toString());
        assertEquals(409, rechazo.statusCode());
        assertEquals("PERSONA_CON_TARJETA", json(rechazo).path("codigo").asText());
        assertEquals("CANCELADA", estadoCaptura(captura.id));
        assertEquals("PERSONA_CON_TARJETA", jdbc.queryForObject(
                "SELECT codigo_confirmacion FROM captura_rfid1 WHERE captura_id=?", String.class, captura.id));
        assertEquals(0, contarUidTemporal(captura.id));
        assertEquals(0, contarAsociacionesPorUid(uidPrevio));
        assertEquals(1, contarAsociacionesPorUid(uidCompetidor));
        assertEquals(1, contarAsociacionesPorPersona("EMPLEADO", empleado.id));
        assertFalse(rechazo.body().contains(uidPrevio));
        assertFalse(rechazo.body().contains(uidCompetidor));
        assertFalse(salida.getAll().contains(uidPrevio));
        assertFalse(salida.getAll().contains(uidCompetidor));
        assertFalse(salida.getAll().contains(TOKEN_DISPOSITIVO));
    }

    private long idAsociacion(String uid) {
        return jdbc.queryForObject("SELECT asociacion_id FROM asociacion_tarjeta_rfid1 WHERE uid_canonico=?",
                Long.class, uid);
    }

    private String estadoAsociacion(long id) {
        return jdbc.queryForObject("SELECT estado FROM asociacion_tarjeta_rfid1 WHERE asociacion_id=?",
                String.class, id);
    }
}
