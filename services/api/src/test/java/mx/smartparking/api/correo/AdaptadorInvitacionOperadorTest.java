package mx.smartparking.api.correo;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

import java.net.ConnectException;
import java.net.SocketTimeoutException;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.mail.MailPreparationException;
import org.springframework.mail.MailSendException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;

class AdaptadorInvitacionOperadorTest {

    private static final String CORREO = "operador@example.test";
    private static final String ENLACE = "https://parking.example.test/activar-operador#token-prueba";
    private static final String REMITENTE = "noreply@example.test";

    private JavaMailSender remitenteSmtp;

    @BeforeEach
    void preparar() {
        remitenteSmtp = mock(JavaMailSender.class);
    }

    @Test
    void enviaEnlaceSinAnadirDatosDeCuentaNiReintentar() {
        AdaptadorInvitacionOperador adaptador = new AdaptadorInvitacionOperador(remitenteSmtp, true, REMITENTE);

        EstadoEnvioInvitacion estado = adaptador.enviar(CORREO, ENLACE);

        assertEquals(EstadoEnvioInvitacion.ENVIADO, estado);
        SimpleMailMessage mensaje = capturarMensaje();
        assertEquals(CORREO, mensaje.getTo()[0]);
        assertEquals(REMITENTE, mensaje.getFrom());
        assertEquals("Activa tu cuenta de Smart Parking", mensaje.getSubject());
        assertTrue(mensaje.getText().contains(ENLACE));
        assertTrue(mensaje.getText().contains("dos horas"));
        assertFalse(mensaje.toString().contains("contrasena"));
        verify(remitenteSmtp, times(1)).send(any(SimpleMailMessage.class));
    }

    @Test
    void smtpDeshabilitadoNoIntentaEnviar() {
        AdaptadorInvitacionOperador adaptador = new AdaptadorInvitacionOperador(remitenteSmtp, false, REMITENTE);

        assertEquals(EstadoEnvioInvitacion.DESHABILITADO, adaptador.enviar(CORREO, ENLACE));
        verify(remitenteSmtp, never()).send(any(SimpleMailMessage.class));
    }

    @Test
    void fallaLocalSeClasificaSinReintento() {
        AdaptadorInvitacionOperador adaptador = new AdaptadorInvitacionOperador(remitenteSmtp, true, REMITENTE);
        doThrow(new MailPreparationException("fallo local de preparación"))
                .when(remitenteSmtp).send(any(SimpleMailMessage.class));

        assertEquals(EstadoEnvioInvitacion.FALLIDO, adaptador.enviar(CORREO, ENLACE));
        verify(remitenteSmtp, times(1)).send(any(SimpleMailMessage.class));
    }

    @Test
    void conexionRechazadaSeClasificaComoFallida() {
        AdaptadorInvitacionOperador adaptador = new AdaptadorInvitacionOperador(remitenteSmtp, true, REMITENTE);
        doThrow(new MailSendException("conexión rechazada", new ConnectException("Connection refused")))
                .when(remitenteSmtp).send(any(SimpleMailMessage.class));

        assertEquals(EstadoEnvioInvitacion.FALLIDO, adaptador.enviar(CORREO, ENLACE));
        verify(remitenteSmtp, times(1)).send(any(SimpleMailMessage.class));
    }

    @Test
    void transporteAmbiguoSeClasificaComoDesconocidoSinReintento() {
        AdaptadorInvitacionOperador adaptador = new AdaptadorInvitacionOperador(remitenteSmtp, true, REMITENTE);
        doThrow(new MailSendException("resultado incierto"))
                .when(remitenteSmtp).send(any(SimpleMailMessage.class));

        assertEquals(EstadoEnvioInvitacion.DESCONOCIDO, adaptador.enviar(CORREO, ENLACE));
        verify(remitenteSmtp, times(1)).send(any(SimpleMailMessage.class));
    }

    @Test
    void timeoutSeClasificaComoDesconocidoSinReintento() {
        AdaptadorInvitacionOperador adaptador = new AdaptadorInvitacionOperador(remitenteSmtp, true, REMITENTE);
        doThrow(new MailSendException("tiempo de espera", new SocketTimeoutException("Read timed out")))
                .when(remitenteSmtp).send(any(SimpleMailMessage.class));

        assertEquals(EstadoEnvioInvitacion.DESCONOCIDO, adaptador.enviar(CORREO, ENLACE));
        verify(remitenteSmtp, times(1)).send(any(SimpleMailMessage.class));
    }

    @Test
    void rechazaSaltosDeLineaAntesDeEnviar() {
        AdaptadorInvitacionOperador adaptador = new AdaptadorInvitacionOperador(remitenteSmtp, true, REMITENTE);

        assertEquals(EstadoEnvioInvitacion.FALLIDO, adaptador.enviar(CORREO + "\r\nBcc:otro@example.test", ENLACE));
        verify(remitenteSmtp, never()).send(any(SimpleMailMessage.class));
    }

    private SimpleMailMessage capturarMensaje() {
        ArgumentCaptor<SimpleMailMessage> capturador = ArgumentCaptor.forClass(SimpleMailMessage.class);
        verify(remitenteSmtp).send(capturador.capture());
        return capturador.getValue();
    }
}
