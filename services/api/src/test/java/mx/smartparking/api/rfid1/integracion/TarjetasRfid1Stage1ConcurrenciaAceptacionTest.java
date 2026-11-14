package mx.smartparking.api.rfid1.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataIntegrityViolationException;

@ExtendWith(OutputCaptureExtension.class)
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@EnabledIfSystemProperty(named = "smartparking.integration.disposable", matches = "true")
class TarjetasRfid1Stage1ConcurrenciaAceptacionTest extends TarjetasRfid1Stage1TestSupport {

    @Test
    void inicioLecturaConfirmacionYUnicidadResistenCarreras(CapturedOutput salida) throws Exception {
        Api duenoA = nuevaSesionDueno();
        Api duenoB = nuevaSesionDueno();
        Persona idempotente = crearEmpleado("rfid-stage1-idempotencia-inicio");
        String claveInicio = UUID.randomUUID().toString();
        Intento primerInicio = iniciar(duenoA, idempotente, claveInicio);
        Intento reintentoInicio = iniciar(duenoA, idempotente, claveInicio);
        assertEquals(201, primerInicio.respuesta().statusCode());
        assertEquals(201, reintentoInicio.respuesta().statusCode());
        String idIdempotente = texto(json(primerInicio.respuesta()), "capturaId");
        assertEquals(idIdempotente, texto(json(reintentoInicio.respuesta()), "capturaId"));
        assertEquals(1, jdbc.queryForObject(
                "SELECT count(*) FROM captura_rfid1 WHERE captura_id=?", Integer.class, idIdempotente));
        assertEquals(204, cancelarCaptura(duenoA, idIdempotente).statusCode());

        Persona mismoObjetivo = crearEmpleado("rfid-stage1-carrera-mismo-objetivo");
        List<Intento> inicios = competir(
                () -> iniciar(duenoA, mismoObjetivo), () -> iniciar(duenoB, mismoObjetivo));
        assertEquals(1, inicios.stream().filter(intento -> intento.respuesta().statusCode() == 201).count());
        assertEquals(1, inicios.stream().filter(intento -> intento.respuesta().statusCode() == 409).count());
        Intento ganador = inicios.stream().filter(intento -> intento.respuesta().statusCode() == 201)
                .findFirst().orElseThrow();
        String capturaId = texto(json(ganador.respuesta()), "capturaId");
        assertEquals(1, jdbc.queryForObject(
                "SELECT count(*) FROM captura_rfid1 WHERE estado IN ('PENDIENTE','ESCANEANDO','VISTA_PREVIA')",
                Integer.class));
        assertEquals(204, cancelarCaptura(ganador.api(), capturaId).statusCode());

        Persona objetivo = crearEmpleado("rfid-stage1-carrera-lectura");
        Captura captura = crearCaptura(dueno, objetivo.tipoEntidad, objetivo.codigo);
        iniciarCaptura(captura.id);
        String uid = "C5C6C7C8";
        List<java.net.http.HttpResponse<String>> lecturas = competir(
                () -> enviarLectura(captura.id, "3001", uid),
                () -> enviarLectura(captura.id, "3002", uid));
        assertEquals(1, lecturas.stream().filter(respuesta -> respuesta.statusCode() == 200).count());
        assertEquals(1, lecturas.stream().filter(respuesta -> respuesta.statusCode() == 409).count());
        assertEquals(1, contarUidTemporal(captura.id));
        assertEquals(0, contarAsociacionesPorPersona("EMPLEADO", objetivo.id));

        String clave = UUID.randomUUID().toString();
        List<java.net.http.HttpResponse<String>> confirmaciones = competir(
                () -> dueno.confirmar(captura.id, clave), () -> dueno.confirmar(captura.id, clave));
        assertTrue(confirmaciones.stream().allMatch(respuesta -> respuesta.statusCode() == 200));
        assertEquals(json(confirmaciones.get(0)).path("asociacionId").asLong(),
                json(confirmaciones.get(1)).path("asociacionId").asLong());
        assertEquals(1, contarAsociacionesPorPersona("EMPLEADO", objetivo.id));
        assertEquals(0, contarUidTemporal(captura.id));

        competirConfirmacionCancelacionYExpiracion();
        competirIndicesAsociacion();
        for (String uidPrueba : List.of("C5C6C7C8", "D5D6D7D8", "E5E6E7E8", "91A2B3C4", "92A2B3C4",
                "93A2B3C4", "94A2B3C4", "95A2B3C4")) {
            assertFalse(salida.getAll().contains(uidPrueba));
        }
        assertFalse(salida.getAll().contains(TOKEN_DISPOSITIVO));
    }
    private void competirConfirmacionCancelacionYExpiracion() throws Exception {
        Persona persona = crearEmpleado("rfid-stage1-carrera-final");
        Captura captura = crearCaptura(dueno, persona.tipoEntidad, persona.codigo);
        iniciarCaptura(captura.id);
        String uid = "D5D6D7D8";
        assertEquals(200, leer(captura.id, uid, "4001").estado);
        String clave = UUID.randomUUID().toString();
        List<java.net.http.HttpResponse<String>> resultados = competir(
                () -> dueno.confirmar(captura.id, clave), () -> dueno.cancelarCaptura(captura.id));
        assertTrue(resultados.stream().allMatch(respuesta -> respuesta.statusCode() == 200
                || respuesta.statusCode() == 204 || respuesta.statusCode() == 409));
        assertEquals(0, contarUidTemporal(captura.id));
        if ("COMPLETADA".equals(estadoCaptura(captura.id))) {
            assertEquals(1, contarAsociacionesPorPersona("EMPLEADO", persona.id));
        } else {
            assertEquals("CANCELADA", estadoCaptura(captura.id));
            assertEquals(0, contarAsociacionesPorPersona("EMPLEADO", persona.id));
        }

        Persona expirada = crearEmpleado("rfid-stage1-carrera-expirada");
        Captura expira = crearCaptura(dueno, expirada.tipoEntidad, expirada.codigo);
        iniciarCaptura(expira.id);
        String uidExpira = "E5E6E7E8";
        assertEquals(200, leer(expira.id, uidExpira, "4002").estado);
        jdbc.update("UPDATE captura_rfid1 SET previsualizada_en=now()-interval '301 seconds', "
                + "confirmacion_vence_en=now()-interval '1 second' WHERE captura_id=?", expira.id);
        assertEquals(409, dueno.confirmar(expira.id, UUID.randomUUID().toString()).statusCode());
        assertTrue(esperarEstado(expira.id, "EXPIRADA", Duration.ofSeconds(5)));
        assertEquals(0, contarUidTemporal(expira.id));
        assertEquals(0, contarAsociacionesPorPersona("EMPLEADO", expirada.id));
    }

    private void competirIndicesAsociacion() throws Exception {
        // V12 mantiene captura_rfid1_activa_uq por lector e incluye VISTA_PREVIA; el CHECK lector=RFID1
        // impide dos previews activos válidos. Aquí se prueba la reserva HTTP del lector y, por JDBC,
        // las carreras de unicidad de las asociaciones sin relajar ese CHECK ni el índice activo.
        Persona mismoCliente = crearCliente("rfid-stage1-db-persona");
        List<Boolean> personaGana = competir(
                () -> insertarTarjeta("91A2B3C4", mismoCliente.clienteId),
                () -> insertarTarjeta("92A2B3C4", mismoCliente.clienteId));
        assertEquals(1, personaGana.stream().filter(Boolean::booleanValue).count());
        assertEquals(1, contarAsociacionesPorPersona("CLIENTE", mismoCliente.clienteId));

        Persona otroCliente = crearCliente("rfid-stage1-db-uid");
        Persona empleado = crearEmpleado("rfid-stage1-db-uid-emp");
        List<Boolean> uidGana = competir(
                () -> insertarTarjeta("93A2B3C4", otroCliente.clienteId),
                () -> insertarTarjetaEmpleado("93A2B3C4", empleado.id));
        assertEquals(1, uidGana.stream().filter(Boolean::booleanValue).count());
        assertEquals(1, contarAsociacionesPorUid("93A2B3C4"));

        Persona mismoEmpleado = crearEmpleado("rfid-stage1-db-empleado");
        List<Boolean> empleadoGana = competir(
                () -> insertarTarjetaEmpleado("94A2B3C4", mismoEmpleado.id),
                () -> insertarTarjetaEmpleado("95A2B3C4", mismoEmpleado.id));
        assertEquals(1, empleadoGana.stream().filter(Boolean::booleanValue).count());
        assertEquals(1, contarAsociacionesPorPersona("EMPLEADO", mismoEmpleado.id));
    }





    private boolean insertarTarjeta(String uid, UUID clienteId) {
        try {
            jdbc.update("INSERT INTO asociacion_tarjeta_rfid1(uid_canonico,cliente_id) VALUES (?,?)", uid, clienteId);
            return true;
        } catch (DataIntegrityViolationException conflicto) {
            return false;
        }
    }

    private boolean insertarTarjetaEmpleado(String uid, Long empleadoId) {
        try {
            jdbc.update("INSERT INTO asociacion_tarjeta_rfid1(uid_canonico,empleado_id) VALUES (?,?)", uid, empleadoId);
            return true;
        } catch (DataIntegrityViolationException conflicto) {
            return false;
        }
    }

    private Intento iniciar(Api api, Persona persona) throws Exception {
        return iniciar(api, persona, UUID.randomUUID().toString());
    }

    private Intento iniciar(Api api, Persona persona, String clave) throws Exception {
        HttpResponse<String> respuesta = api.post("/api/v1/rfid-1/capturas",
                Map.of("tipoEntidad", persona.tipoEntidad, "codigoPersona", persona.codigo),
                Map.of(CSRF, api.csrf(), "Idempotency-Key", clave));
        return new Intento(api, respuesta);
    }

    @SafeVarargs
    private static <T> List<T> competir(Callable<T>... operaciones) throws Exception {
        ExecutorService executor = Executors.newFixedThreadPool(operaciones.length);
        CountDownLatch preparadas = new CountDownLatch(operaciones.length);
        CountDownLatch iniciar = new CountDownLatch(1);
        List<Future<T>> futuras = new ArrayList<>();
        try {
            for (Callable<T> operacion : operaciones) {
                futuras.add(executor.submit(() -> {
                    preparadas.countDown();
                    if (!iniciar.await(5, TimeUnit.SECONDS)) {
                        throw new IllegalStateException("La barrera concurrente agotó su espera.");
                    }
                    return operacion.call();
                }));
            }
            assertTrue(preparadas.await(5, TimeUnit.SECONDS));
            iniciar.countDown();
            List<T> resultados = new ArrayList<>();
            for (Future<T> futura : futuras) {
                resultados.add(futura.get(20, TimeUnit.SECONDS));
            }
            return resultados;
        } finally {
            iniciar.countDown();
            executor.shutdownNow();
        }
    }

    private record Intento(Api api, java.net.http.HttpResponse<String> respuesta) {
    }
}
