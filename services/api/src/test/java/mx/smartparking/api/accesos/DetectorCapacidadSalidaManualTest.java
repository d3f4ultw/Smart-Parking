package mx.smartparking.api.accesos;

import static org.junit.jupiter.api.Assertions.*;

import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Base64;
import java.util.HexFormat;
import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.junit.jupiter.api.Test;

/** Verifica la vigencia y el consumo seguro del desafío sin consultar hardware. */
class DetectorCapacidadSalidaManualTest {
    private final byte[] clave = new byte[32];
    private final AtomicLong reloj = new AtomicLong();
    private final DetectorCapacidadSalidaManual detector;
    private final String boot = Base64.getUrlEncoder().withoutPadding().encodeToString(new byte[16]);

    DetectorCapacidadSalidaManualTest() {
        new SecureRandom().nextBytes(clave);
        detector = new DetectorCapacidadSalidaManual(new AutenticadorSalidaManual(HexFormat.of().formatHex(clave)),
                reloj::get);
    }

    @Test
    void pruebaValidaEsTemporalYNoPuedeRepetirse() {
        assertFalse(detector.disponibilidad().disponible());
        String desafio = detector.crearDesafio();
        String firma = firmar(boot, desafio, clave);
        assertTrue(detector.confirmar(desafio, boot, firma));
        assertEquals(8000, detector.disponibilidad().vigenciaRestanteMs());
        reloj.addAndGet(TimeUnit.MILLISECONDS.toNanos(3100));
        assertEquals(4900, detector.disponibilidad().vigenciaRestanteMs());
        assertFalse(detector.confirmar(desafio, boot, firma));
        assertFalse(detector.disponibilidad().disponible());
    }

    @Test
    void caducidadYReinicioNoMantienenCapacidad() {
        String desafio = detector.crearDesafio();
        assertTrue(detector.confirmar(desafio, boot, firmar(boot, desafio, clave)));
        reloj.addAndGet(TimeUnit.SECONDS.toNanos(8));
        assertFalse(detector.disponibilidad().disponible());
        String nuevo = detector.crearDesafio();
        reloj.addAndGet(TimeUnit.SECONDS.toNanos(5));
        assertFalse(detector.confirmar(nuevo, boot, firmar(boot, nuevo, clave)));
        DetectorCapacidadSalidaManual reiniciado = new DetectorCapacidadSalidaManual(
                new AutenticadorSalidaManual(HexFormat.of().formatHex(clave)), reloj::get);
        assertFalse(reiniciado.disponibilidad().disponible());
        assertFalse(reiniciado.confirmar(nuevo, boot, firmar(boot, nuevo, clave)));
    }

    @Test
    void firmaOIdentificadorIncorrectoInvalidaCapacidadAnterior() {
        String primero = detector.crearDesafio();
        assertTrue(detector.confirmar(primero, boot, firmar(boot, primero, clave)));
        String siguiente = detector.crearDesafio();
        byte[] otraClave = new byte[32];
        new SecureRandom().nextBytes(otraClave);
        assertFalse(detector.confirmar(siguiente, boot, firmar(boot, siguiente, otraClave)));
        assertFalse(detector.disponibilidad().disponible());
        String otro = detector.crearDesafio();
        assertFalse(detector.confirmar(otro, "invalido", firmar(boot, otro, clave)));
        assertFalse(detector.disponibilidad().disponible());
    }

    @Test
    void desconexionImpideQueUnDesafioPrevioRestaureDisponibilidad() {
        String desafio = detector.crearDesafio();
        detector.invalidar();
        assertFalse(detector.confirmar(desafio, boot, firmar(boot, desafio, clave)));
        assertFalse(detector.disponibilidad().disponible());
    }

    @Test
    void cambioDeBootInvalidaLaCapacidad() {
        String desafio = detector.crearDesafio();
        assertTrue(detector.confirmar(desafio, boot, firmar(boot, desafio, clave)));
        assertTrue(detector.disponibleParaBoot(boot));
        byte[] otrosBytes = new byte[16];
        otrosBytes[0] = 1;
        String otroBoot = Base64.getUrlEncoder().withoutPadding().encodeToString(otrosBytes);
        assertFalse(detector.disponibleParaBoot(otroBoot));
        assertFalse(detector.disponibilidad().disponible());
    }

    @Test
    void memoriaDeDesafiosEsAcotadaYLaClaveAusenteFallaCerrada() {
        String antiguo = detector.crearDesafio();
        for (int i = 0; i < 64; i++) detector.crearDesafio();
        assertFalse(detector.confirmar(antiguo, boot, firmar(boot, antiguo, clave)));
        var sinClave = new DetectorCapacidadSalidaManual(new AutenticadorSalidaManual(""), reloj::get);
        assertNull(sinClave.crearDesafio());
        assertFalse(sinClave.disponibilidad().disponible());
        assertFalse(sinClave.confirmar(antiguo, boot, firmar(boot, antiguo, clave)));
    }

    @Test
    void dosRespuestasConcurrentesConsumenDesafioUnaVez() throws Exception {
        String desafio = detector.crearDesafio();
        String firma = firmar(boot, desafio, clave);
        try (var pool = Executors.newFixedThreadPool(2)) {
            var resultados = pool.invokeAll(List.<java.util.concurrent.Callable<Boolean>>of(
                    () -> detector.confirmar(desafio, boot, firma),
                    () -> detector.confirmar(desafio, boot, firma)));
            long validos = 0;
            for (var resultado : resultados) if (resultado.get()) validos++;
            assertEquals(1, validos);
        }
        // El intento repetido invalida la disponibilidad, por seguridad.
        assertFalse(detector.disponibilidad().disponible());
    }

    static String firmar(String boot, String desafio, byte[] clave) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(clave, "HmacSHA256"));
            byte[] datos = ("smartparking.manual.v1|PROBE|" + boot + "|" + desafio)
                    .getBytes(StandardCharsets.US_ASCII);
            return Base64.getUrlEncoder().withoutPadding().encodeToString(Arrays.copyOf(mac.doFinal(datos), 12));
        } catch (java.security.GeneralSecurityException excepcion) {
            throw new IllegalStateException(excepcion);
        }
    }
}
