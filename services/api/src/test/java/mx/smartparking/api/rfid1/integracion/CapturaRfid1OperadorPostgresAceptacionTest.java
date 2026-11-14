package mx.smartparking.api.rfid1.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.Locale;
import java.util.UUID;
import mx.smartparking.api.rfid1.servicio.ServicioConfirmacionRfid1;
import mx.smartparking.api.rfid1.servicio.ServicioRfid1;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

/** Comprueba el ciclo OPERADOR contra PostgreSQL desechable y el CHECK de V11 real. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@EnabledIfSystemProperty(named = "smartparking.integration.disposable", matches = "true")
class CapturaRfid1OperadorPostgresAceptacionTest extends TarjetasRfid1Stage1TestSupport {

    @Autowired
    private ServicioRfid1 servicioCapturas;

    @Autowired
    private ServicioConfirmacionRfid1 servicioConfirmacion;

    @Test
    void revisionCeroDeSesionOperadorCompletaCapturaConRevisionPositivaSinLigarlaAlDueno() throws Exception {
        String sufijo = UUID.randomUUID().toString();
        Persona empleado = crearEmpleado("rfid-operador-" + sufijo);
        Persona empleadoCancelacion = crearEmpleado("rfid-operador-cancelacion-" + sufijo);
        UUID cuentaOperadorId = UUID.randomUUID();
        String correo = "operador-rfid-" + sufijo + "@example.invalid";
        Timestamp ahora = Timestamp.from(Instant.now());

        jdbc.update("UPDATE empleado SET correo = ?, correo_normalizado = ? WHERE id = ?",
                correo, correo, empleado.empleadoId());
        jdbc.update("""
                INSERT INTO cuenta (
                    id, nombres, primer_apellido, segundo_apellido, correo, correo_normalizado,
                    rol, estado, hash_contrasena_acceso, revision_acceso, empleado_id, creada_en, actualizada_en)
                VALUES (?, 'Operador RFID', 'Prueba', NULL, ?, ?, 'OPERADOR', 'ACTIVA',
                        'hash-sintetico-no-autenticable', 1, ?, ?, ?)
                """, cuentaOperadorId, correo, correo, empleado.empleadoId(), ahora, ahora);
        jdbc.update("UPDATE configuracion_estacionamiento SET revision_propietario = 37 WHERE id = 1");

        PrincipalPropietario operador = new PrincipalPropietario(
                cuentaOperadorId, RolCuenta.OPERADOR, 1, 0, correo);
        String huellaSesion = "a".repeat(64);
        String claveInicio = UUID.randomUUID().toString();
        var captura = servicioCapturas.crearCaptura(
                "EMPLEADO", empleado.codigoPersona(), claveInicio, huellaSesion, operador);

        assertEquals("PENDIENTE", captura.estado());
        assertEquals(0, operador.revisionPropietario(), "La sesión OPERADOR debe conservar su revisión cero.");
        assertEquals(1L, jdbc.queryForObject("""
                SELECT revision_propietario FROM captura_rfid1 WHERE captura_id = ?
                """, Long.class, captura.capturaId()));
        assertTrue(jdbc.queryForObject("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'captura_rfid1_revisiones_ck' AND convalidated
                )
                """, Boolean.class), "La regresión debe ejecutarse con el CHECK original habilitado.");
        assertEquals(captura.capturaId(),
                servicioCapturas.consultarCapturaActiva(huellaSesion, operador).orElseThrow().capturaId());

        var repetida = servicioCapturas.crearCaptura(
                "EMPLEADO", empleado.codigoPersona(), claveInicio, huellaSesion, operador);
        assertEquals(captura.capturaId(), repetida.capturaId(), "El replay no debe insertar otra captura.");
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM captura_rfid1
                WHERE propietario_cuenta_id = ? AND huella_sesion = ?
                """, Integer.class, cuentaOperadorId, huellaSesion));

        iniciarCaptura(captura.capturaId());
        String uidSintetico = UUID.randomUUID().toString().replace("-", "")
                .substring(0, 8).toUpperCase(Locale.ROOT);
        Resultado lectura = leer(captura.capturaId(), uidSintetico, "00A1");
        assertEquals(200, lectura.estado);
        assertFalse(lectura.texto.contains(uidSintetico), "La respuesta del lector no debe exponer la UID.");
        var vistaPrevia = servicioConfirmacion.consultarVistaPrevia(captura.capturaId(), huellaSesion, operador);
        assertEquals(uidSintetico, vistaPrevia.uid());

        var confirmacion = servicioConfirmacion.confirmar(
                captura.capturaId(), huellaSesion, "confirmacion-operador-" + UUID.randomUUID(), operador);

        assertEquals("COMPLETADA", confirmacion.estado());
        assertEquals(1L, jdbc.queryForObject("""
                SELECT count(*) FROM asociacion_tarjeta_rfid1 WHERE empleado_id = ? AND uid_canonico = ?
                """, Long.class, empleado.empleadoId(), uidSintetico));

        var capturaCancelacion = servicioCapturas.crearCaptura(
                "EMPLEADO", empleadoCancelacion.codigoPersona(), UUID.randomUUID().toString(),
                huellaSesion, operador);
        assertEquals("PENDIENTE", estadoCaptura(capturaCancelacion.capturaId()));
        assertEquals(1L, jdbc.queryForObject("""
                SELECT revision_propietario FROM captura_rfid1 WHERE captura_id = ?
                """, Long.class, capturaCancelacion.capturaId()));

        servicioCapturas.cancelarCaptura(capturaCancelacion.capturaId(), huellaSesion, operador);
        servicioCapturas.cancelarCaptura(capturaCancelacion.capturaId(), huellaSesion, operador);

        assertEquals("CANCELADA", estadoCaptura(capturaCancelacion.capturaId()));
        assertEquals(0L, jdbc.queryForObject("""
                SELECT count(*) FROM asociacion_tarjeta_rfid1 WHERE empleado_id = ?
                """, Long.class, empleadoCancelacion.empleadoId()));
        assertEquals(0L, jdbc.queryForObject("""
                SELECT count(*) FROM uid_temporal_rfid1 WHERE captura_id = ?
                """, Long.class, capturaCancelacion.capturaId()));
    }
}
