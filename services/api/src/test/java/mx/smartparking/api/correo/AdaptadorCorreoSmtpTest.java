package mx.smartparking.api.correo;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

import java.net.ConnectException;
import java.net.SocketTimeoutException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.mail.MailPreparationException;
import org.springframework.mail.MailSendException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;

class AdaptadorCorreoSmtpTest {

    private static final String CORREO = "propietario@example.test";
    private static final String NOMBRE = "Ana López García";
    private static final String ESTACIONAMIENTO = "Centro";
    private static final String REMITENTE = "smartparking@example.test";
    private static final String CONTRASENA_ACCESO = "Acceso-Privado-2026";
    private static final String CONTRASENA_ADMINISTRATIVA = "Administracion-Segura-2026";
    private static final String GRANT_TRANSFERENCIA = "grant-secreto-2026";

    private JavaMailSender remitenteSmtp;

    @BeforeEach
    void preparar() {
        remitenteSmtp = mock(JavaMailSender.class);
    }

    @Test
    void bienvenidaNoIncluyeSecretosEnLaPlantilla() {
        AdaptadorCorreoSmtp adaptador = new AdaptadorCorreoSmtp(remitenteSmtp, true, REMITENTE);

        EstadoAviso estado = adaptador.enviarBienvenida(CORREO, NOMBRE, ESTACIONAMIENTO);

        assertEquals(EstadoAviso.ENVIADO, estado);
        SimpleMailMessage mensaje = capturarMensaje();
        assertEquals(CORREO, mensaje.getTo()[0]);
        assertEquals(REMITENTE, mensaje.getFrom());
        assertEquals("Tu estacionamiento ya está configurado", mensaje.getSubject());
        assertTrue(mensaje.getText().contains("Hola, " + NOMBRE));
        assertTrue(mensaje.getText().contains(NOMBRE));
        assertTrue(mensaje.getText().contains(ESTACIONAMIENTO));
        assertTrue(mensaje.getText().contains("Por seguridad, nunca compartas tu contraseña por correo."));
        assertFalse(mensaje.getText().contains(CONTRASENA_ACCESO));
        assertFalse(mensaje.getText().contains(CONTRASENA_ADMINISTRATIVA));
        assertFalse(mensaje.getText().contains(GRANT_TRANSFERENCIA));
    }

    @Test
    void avisoDeDesvinculacionNoIncluyeSecretosEnLaPlantilla() {
        AdaptadorCorreoSmtp adaptador = new AdaptadorCorreoSmtp(remitenteSmtp, true, REMITENTE);

        EstadoAviso estado = adaptador.notificarDesvinculacion(CORREO, NOMBRE, ESTACIONAMIENTO);

        assertEquals(EstadoAviso.ENVIADO, estado);
        SimpleMailMessage mensaje = capturarMensaje();
        assertEquals(CORREO, mensaje.getTo()[0]);
        assertEquals("Cambió tu acceso a Smart Parking", mensaje.getSubject());
        assertTrue(mensaje.getText().contains("Hola, " + NOMBRE));
        assertTrue(mensaje.getText().contains("«" + ESTACIONAMIENTO + "»"));
        assertTrue(mensaje.getText().contains("Se quitó tu acceso como propietario"));
        assertTrue(mensaje.getText().contains("Por seguridad, nunca compartas tu contraseña por correo."));
        assertFalse(mensaje.getText().contains(CONTRASENA_ACCESO));
        assertFalse(mensaje.getText().contains(CONTRASENA_ADMINISTRATIVA));
        assertFalse(mensaje.getText().contains(GRANT_TRANSFERENCIA));
    }

    @Test
    void correoDeshabilitadoNoContactaElServidor() {
        AdaptadorCorreoSmtp adaptador = new AdaptadorCorreoSmtp(remitenteSmtp, false, REMITENTE);

        EstadoAviso estado = adaptador.enviarBienvenida(CORREO, NOMBRE, ESTACIONAMIENTO);

        assertEquals(EstadoAviso.DESHABILITADO, estado);
        verify(remitenteSmtp, never()).send(any(SimpleMailMessage.class));
    }

    @Test
    void falloConocidoAntesDelEnvioSeDevuelveSinPropagarLaExcepcion() {
        AdaptadorCorreoSmtp adaptador = new AdaptadorCorreoSmtp(remitenteSmtp, true, REMITENTE);
        doThrow(new MailPreparationException("fallo local de preparación"))
                .when(remitenteSmtp).send(any(SimpleMailMessage.class));

        EstadoAviso estado = adaptador.enviarBienvenida(CORREO, NOMBRE, ESTACIONAMIENTO);

        assertEquals(EstadoAviso.FALLIDO, estado);
        verify(remitenteSmtp, times(1)).send(any(SimpleMailMessage.class));
    }

    @Test
    void falloDeTransporteAmbiguoSeDevuelveSinReintentoNiExcepcion() {
        AdaptadorCorreoSmtp adaptador = new AdaptadorCorreoSmtp(remitenteSmtp, true, REMITENTE);
        doThrow(new MailSendException("resultado SMTP incierto"))
                .when(remitenteSmtp).send(any(SimpleMailMessage.class));

        EstadoAviso estado = adaptador.notificarDesvinculacion(CORREO, NOMBRE, ESTACIONAMIENTO);

        assertEquals(EstadoAviso.DESCONOCIDO, estado);
        verify(remitenteSmtp, times(1)).send(any(SimpleMailMessage.class));
    }

    @Test
    void conexionRechazadaAntesDeLaAceptacionSeDevuelveComoFallidoSinReintento() {
        AdaptadorCorreoSmtp adaptador = new AdaptadorCorreoSmtp(remitenteSmtp, true, REMITENTE);
        doThrow(new MailSendException("No fue posible conectar con SMTP", new ConnectException("Connection refused")))
                .when(remitenteSmtp).send(any(SimpleMailMessage.class));

        EstadoAviso estado = adaptador.enviarBienvenida(CORREO, NOMBRE, ESTACIONAMIENTO);

        assertEquals(EstadoAviso.FALLIDO, estado);
        verify(remitenteSmtp, times(1)).send(any(SimpleMailMessage.class));
    }

    @Test
    void tiempoDeEsperaAgotadoSeDevuelveComoDesconocidoSinReintento() {
        AdaptadorCorreoSmtp adaptador = new AdaptadorCorreoSmtp(remitenteSmtp, true, REMITENTE);
        doThrow(new MailSendException("Tiempo de espera agotado", new SocketTimeoutException("Read timed out")))
                .when(remitenteSmtp).send(any(SimpleMailMessage.class));

        EstadoAviso estado = adaptador.notificarDesvinculacion(CORREO, NOMBRE, ESTACIONAMIENTO);

        assertEquals(EstadoAviso.DESCONOCIDO, estado);
        verify(remitenteSmtp, times(1)).send(any(SimpleMailMessage.class));
    }

    @Test
    void direccionRemitenteInvalidaFallaAntesDeIntentarSmtp() {
        AdaptadorCorreoSmtp adaptador = new AdaptadorCorreoSmtp(remitenteSmtp, true, "remitente\r\ninvalido");

        EstadoAviso estado = adaptador.enviarBienvenida(CORREO, NOMBRE, ESTACIONAMIENTO);

        assertEquals(EstadoAviso.FALLIDO, estado);
        verify(remitenteSmtp, never()).send(any(SimpleMailMessage.class));
    }

    private SimpleMailMessage capturarMensaje() {
        ArgumentCaptor<SimpleMailMessage> capturador = ArgumentCaptor.forClass(SimpleMailMessage.class);
        verify(remitenteSmtp).send(capturador.capture());
        SimpleMailMessage mensaje = capturador.getValue();
        assertNotNull(mensaje.getText());
        return mensaje;
    }
}
