package mx.smartparking.api.eventos;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.io.IOException;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyEmitter;
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyEmitter.DataWithMediaType;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/** Prueba la entrega con el handler interno de Spring WebMVC 7.0.10, sin modificar la API. */
class ServicioEventosAdministracionEntregaTest {
    private static final String VISION = "vision.ocupacion.actualizada";
    private static final String EMPLEADOS = "empleado.directorio.actualizado";
    private static final String OPERADORES = "operador.directorio.actualizado";
    private static final String ACCESOS = "acceso.historial.actualizado";
    private static final String CLIENTE = "cliente.registrado";
    private static final String MEMBRESIA = "membresia.actualizada";
    private static final String CAPTURA = "rfid1.captura.actualizada";
    private static final String TARJETAS = "rfid1.tarjetas.actualizadas";
    private static final String RESINCRONIZAR = "administracion.directorio.resincronizar";
    private ServicioEventosAdministracion servicio;
    private GestorSesionesPropietario gestor;
    private RepositorioCuentas cuentas;
    private MockHttpSession sesion;
    private PrincipalPropietario dueno;

    @BeforeEach
    void preparar() {
        gestor = new GestorSesionesPropietario();
        cuentas = mock(RepositorioCuentas.class);
        servicio = new ServicioEventosAdministracion(
                gestor, cuentas, System::nanoTime, UUID::randomUUID, mock(ScheduledExecutorService.class));
        sesion = new MockHttpSession();
        dueno = new PrincipalPropietario(UUID.randomUUID(), RolCuenta.DUENO, 1, 1, "dueno@example.test");
        gestor.registrar(sesion, dueno);
        when(cuentas.sesionVigente(
                dueno.cuentaId(), dueno.revisionAcceso(), dueno.rol().name(), dueno.revisionPropietario()))
                .thenReturn(true);
    }

    @AfterEach
    void detener() {
        servicio.detener();
    }

    @Test
    void entregaEnOrdenConSuscriptorLentoYReproduccionDuranteLaPublicacion() throws Exception {
        String cursorInicial = servicio.cursorActual();
        Receptor lento = new Receptor(true, false);
        Receptor rapido = new Receptor(false, false);
        conectar(cursorInicial, lento);
        conectar(cursorInicial, rapido);
        ExecutorService ejecutor = Executors.newFixedThreadPool(2);
        try {
            Future<?> primero = ejecutor.submit(servicio::publicarVisionActualizada);
            assertTrue(lento.entrada.await(5, TimeUnit.SECONDS), "El envío Vision debe alcanzar la barrera.");
            CountDownLatch segundoIniciado = new CountDownLatch(1);
            Future<?> segundo = ejecutor.submit(() -> {
                segundoIniciado.countDown();
                servicio.publicarDirectorioActualizado();
            });
            assertTrue(segundoIniciado.await(5, TimeUnit.SECONDS));
            assertThrows(TimeoutException.class, () -> segundo.get(150, TimeUnit.MILLISECONDS));
            String cursorVision = servicio.cursorActual();
            assertEquals(secuencia(cursorInicial) + 1, secuencia(cursorVision));

            // El registro y el replay siguen disponibles mientras otro emisor espera I/O.
            Receptor duranteEnvio = new Receptor(false, false);
            conectar(cursorInicial, duranteEnvio);
            assertEquals(List.of(new Evento(cursorVision, VISION, "{}")), duranteEnvio.eventos);

            lento.liberar.countDown();
            primero.get(5, TimeUnit.SECONDS);
            segundo.get(5, TimeUnit.SECONDS);
            String cursorEmpleado = servicio.cursorActual();
            assertEquals(secuencia(cursorVision) + 1, secuencia(cursorEmpleado));
            List<Evento> esperados = List.of(
                    new Evento(cursorVision, VISION, "{}"), new Evento(cursorEmpleado, EMPLEADOS, "{}"));
            assertEquals(esperados, lento.eventos);
            assertEquals(esperados, rapido.eventos);
            assertEquals(esperados, duranteEnvio.eventos);
        } finally {
            lento.liberar.countDown();
            ejecutor.shutdownNow();
            assertTrue(ejecutor.awaitTermination(5, TimeUnit.SECONDS));
        }
    }

    @Test
    void falloDeEnvioNoInterrumpeOtrosDestinosYElCursorPermiteReplay() throws Exception {
        String cursorInicial = servicio.cursorActual();
        Receptor fallido = new Receptor(false, true);
        Receptor sano = new Receptor(false, false);
        conectar(cursorInicial, fallido);
        conectar(cursorInicial, sano);
        servicio.publicarVisionActualizada();
        String cursorVision = servicio.cursorActual();
        servicio.publicarDirectorioActualizado();
        String cursorEmpleado = servicio.cursorActual();
        List<Evento> esperados = List.of(
                new Evento(cursorVision, VISION, "{}"), new Evento(cursorEmpleado, EMPLEADOS, "{}"));
        assertEquals(1, fallido.fallos);
        assertTrue(fallido.eventos.isEmpty(), "El destino fallido no debe recibir eventos posteriores.");
        assertEquals(esperados, sano.eventos);
        Receptor reconectado = new Receptor(false, false);
        conectar(cursorInicial, reconectado);
        assertEquals(esperados, reconectado.eventos);
    }

    @Test
    void operadorRecibeSoloEventosOperativosEnVivoYEnReplay() throws Exception {
        MockHttpSession sesionOperador = new MockHttpSession();
        PrincipalPropietario operador = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.OPERADOR, 2, 1, "operador@example.test");
        gestor.registrar(sesionOperador, operador);
        when(cuentas.sesionVigente(
                operador.cuentaId(), operador.revisionAcceso(), operador.rol().name(), operador.revisionPropietario()))
                .thenReturn(true);

        String cursorInicial = servicio.cursorActual();
        Receptor operadorVivo = new Receptor(false, false);
        Receptor propietario = new Receptor(false, false);
        conectar(sesionOperador.getId(), operador, cursorInicial, operadorVivo);
        conectar(sesion.getId(), dueno, cursorInicial, propietario);

        List<String> publicados = List.of(VISION, ACCESOS, CLIENTE, MEMBRESIA, CAPTURA, TARJETAS,
                EMPLEADOS, OPERADORES, "directorio.interno.actualizado");
        publicados.forEach(servicio::publicarDirectorioActualizado);

        List<Evento> eventosPropietario = eventos(cursorInicial, publicados);
        List<Evento> eventosOperador = eventos(cursorInicial, List.of(
                VISION, ACCESOS, CLIENTE, MEMBRESIA, CAPTURA, TARJETAS,
                RESINCRONIZAR, RESINCRONIZAR, RESINCRONIZAR));
        assertEquals(eventosPropietario, propietario.eventos);
        assertEquals(eventosOperador, operadorVivo.eventos);

        Receptor operadorReplay = new Receptor(false, false);
        conectar(sesionOperador.getId(), operador, cursorInicial, operadorReplay);
        assertEquals(eventosOperador, operadorReplay.eventos);
    }

    @Test
    void cierreNoInvierteCandadosYFinalizaAlLiberarElEnvio() throws Exception {
        String cursorInicial = servicio.cursorActual();
        Receptor lento = new Receptor(true, false);
        conectar(cursorInicial, lento);
        ExecutorService ejecutor = Executors.newFixedThreadPool(2);
        try {
            Future<?> envio = ejecutor.submit(servicio::publicarVisionActualizada);
            assertTrue(lento.entrada.await(5, TimeUnit.SECONDS));
            CountDownLatch cierreIniciado = new CountDownLatch(1);
            Future<?> cierre = ejecutor.submit(() -> {
                cierreIniciado.countDown();
                servicio.detener();
            });
            assertTrue(cierreIniciado.await(5, TimeUnit.SECONDS));
            assertThrows(TimeoutException.class, () -> cierre.get(150, TimeUnit.MILLISECONDS));
            lento.liberar.countDown();
            envio.get(5, TimeUnit.SECONDS);
            cierre.get(5, TimeUnit.SECONDS);
            ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                    () -> servicio.abrirStream(sesion.getId(), dueno, cursorInicial));
            assertEquals(HttpStatus.SERVICE_UNAVAILABLE, error.estadoHttp());
        } finally {
            lento.liberar.countDown();
            ejecutor.shutdownNow();
            assertTrue(ejecutor.awaitTermination(5, TimeUnit.SECONDS));
        }
    }

    private void conectar(String cursor, Receptor receptor) throws Exception {
        conectar(sesion.getId(), dueno, cursor, receptor);
    }

    private void conectar(
            String idSesion, PrincipalPropietario principal, String cursor, Receptor receptor) throws Exception {
        SseEmitter emisor = servicio.abrirStream(idSesion, principal, cursor);
        Class<?> tipoHandler = Class.forName(ResponseBodyEmitter.class.getName() + "$Handler");
        Object handler = Proxy.newProxyInstance(tipoHandler.getClassLoader(), new Class<?>[] {tipoHandler}, receptor);
        Method inicializar = ResponseBodyEmitter.class.getDeclaredMethod("initialize", tipoHandler);
        inicializar.setAccessible(true);
        inicializar.invoke(emisor, handler);
    }

    private static List<Evento> eventos(String cursorInicial, List<String> nombres) {
        String epoca = cursorInicial.substring(0, cursorInicial.lastIndexOf(':'));
        return java.util.stream.IntStream.range(0, nombres.size())
                .mapToObj(indice -> new Evento(epoca + ":" + (indice + 1), nombres.get(indice), "{}"))
                .toList();
    }

    private static long secuencia(String cursor) {
        return Long.parseLong(cursor.substring(cursor.lastIndexOf(':') + 1));
    }

    private record Evento(String cursor, String nombre, String datos) { }

    /** Simula I/O y solo conserva invalidaciones; no guarda heartbeats ni información de sesión. */
    private static final class Receptor implements InvocationHandler {
        private static final Pattern ID = Pattern.compile("(?m)^id:([^\\r\\n]+)");
        private static final Pattern NOMBRE = Pattern.compile("(?m)^event:([^\\r\\n]+)");
        private static final Pattern DATOS = Pattern.compile("(?m)^data:([^\\r\\n]*)");
        private final List<Evento> eventos = new CopyOnWriteArrayList<>();
        private final CountDownLatch entrada = new CountDownLatch(1);
        private final CountDownLatch liberar = new CountDownLatch(1);
        private final boolean bloquear;
        private final boolean fallar;
        private int fallos;

        private Receptor(boolean bloquear, boolean fallar) {
            this.bloquear = bloquear;
            this.fallar = fallar;
        }

        @Override
        public Object invoke(Object proxy, Method metodo, Object[] argumentos) throws Throwable {
            if (!"send".equals(metodo.getName()) || argumentos == null
                    || argumentos.length != 1 || !(argumentos[0] instanceof Set<?> bloques)) return null;
            StringBuilder texto = new StringBuilder();
            for (Object bloque : bloques) {
                if (bloque instanceof DataWithMediaType dato && dato.getData() instanceof String parte) {
                    texto.append(parte);
                }
            }
            for (String bloqueEvento : texto.toString().split("\\n\\n")) {
                Matcher id = ID.matcher(bloqueEvento);
                Matcher nombre = NOMBRE.matcher(bloqueEvento);
                Matcher datos = DATOS.matcher(bloqueEvento);
                if (!id.find() || !nombre.find() || !datos.find()) continue;
                if (VISION.equals(nombre.group(1)) && bloquear) {
                    entrada.countDown();
                    try {
                        if (!liberar.await(5, TimeUnit.SECONDS)) throw new IOException("Barrera SSE vencida.");
                    } catch (InterruptedException excepcion) {
                        Thread.currentThread().interrupt();
                        throw new IOException("Envío SSE interrumpido.", excepcion);
                    }
                }
                if (VISION.equals(nombre.group(1)) && fallar) {
                    fallos += 1;
                    throw new IOException("Fallo sintético de entrega SSE.");
                }
                eventos.add(new Evento(id.group(1), nombre.group(1), datos.group(1)));
            }
            return null;
        }
    }
}
