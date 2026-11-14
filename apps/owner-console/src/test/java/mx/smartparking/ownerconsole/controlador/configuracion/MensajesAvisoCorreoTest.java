package mx.smartparking.ownerconsole.controlador.configuracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

class MensajesAvisoCorreoTest {

    private static final String BIENVENIDA_ENVIADA = "La configuración está lista y ya puedes entrar. "
            + "Revisa tu correo para encontrar el mensaje de bienvenida.";

    @Test
    void muestraElTextoAprobadoCuandoElAvisoSeEnvio() {
        assertEquals(BIENVENIDA_ENVIADA, MensajesAvisoCorreo.describirBienvenida("ENVIADO"));
    }

    @ParameterizedTest
    @MethodSource("estadosNoExitosos")
    void evitaDetallesTecnicosCuandoNoSeConfirmaElEnvio(String estado, String esperado) {
        String mensaje = MensajesAvisoCorreo.describirBienvenida(estado);

        assertEquals(esperado, mensaje);
        assertFalse(mensaje.contains("SMTP"));
        assertFalse(mensaje.contains("bandeja"));
        assertFalse(mensaje.contains("reintentará"));
        assertTrue(mensaje.startsWith("La configuración está lista y ya puedes entrar"));
    }

    private static Stream<Arguments> estadosNoExitosos() {
        return Stream.of(
                Arguments.of("FALLIDO", "La configuración está lista y ya puedes entrar, pero no pudimos enviar "
                        + "el mensaje de bienvenida."),
                Arguments.of("DESHABILITADO", "La configuración está lista y ya puedes entrar. "
                        + "El mensaje de bienvenida no se envió."),
                Arguments.of("DESCONOCIDO", "La configuración está lista y ya puedes entrar. "
                        + "Si no encuentras el mensaje de bienvenida, revisa el correo no deseado."),
                Arguments.of(null, "La configuración está lista y ya puedes entrar. "
                        + "Si no encuentras el mensaje de bienvenida, revisa el correo no deseado."),
                Arguments.of("NO_RECONOCIDO", "La configuración está lista y ya puedes entrar. "
                        + "Si no recibes el mensaje de bienvenida, revisa tu correo no deseado."));
    }
}
