package mx.smartparking.api.correo;

import java.net.ConnectException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.mail.MailAuthenticationException;
import org.springframework.mail.MailParseException;
import org.springframework.mail.MailPreparationException;
import org.springframework.mail.MailSendException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.stereotype.Component;

/** Intenta enviar correos de bienvenida o de cambio de propietario después de guardar los cambios. */
@Component
public final class AdaptadorCorreoSmtp implements NotificadorCorreo {

    private static final String ASUNTO_BIENVENIDA = "Tu estacionamiento ya está configurado";
    private static final String ASUNTO_DESVINCULACION = "Cambió tu acceso a Smart Parking";

    private final JavaMailSender remitenteSmtp;
    private final boolean habilitado;
    private final String direccionRemitente;

    public AdaptadorCorreoSmtp(
            JavaMailSender remitenteSmtp,
            @Value("${smartparking.correo.habilitado:false}") boolean habilitado,
            @Value("${smartparking.correo.remitente:}") String direccionRemitente) {
        this.remitenteSmtp = remitenteSmtp;
        this.habilitado = habilitado;
        this.direccionRemitente = direccionRemitente;
    }

    @Override
    public EstadoAviso enviarBienvenida(String correo, String nombreCompleto, String nombreEstacionamiento) {
        String cuerpo = "Hola, " + textoSeguro(nombreCompleto, "propietario") + ".\n\n"
                + "Tu estacionamiento «" + textoSeguro(nombreEstacionamiento, "Smart Parking")
                + "» ya está configurado.\n"
                + "Por seguridad, nunca compartas tu contraseña por correo.";
        return enviar(correo, ASUNTO_BIENVENIDA, cuerpo);
    }

    @Override
    public EstadoAviso notificarDesvinculacion(
            String correoAnterior,
            String nombreCompletoAnterior,
            String nombreEstacionamiento) {
        String cuerpo = "Hola, " + textoSeguro(nombreCompletoAnterior, "propietario") + ".\n\n"
                + "Se quitó tu acceso como propietario al estacionamiento «"
                + textoSeguro(nombreEstacionamiento, "Smart Parking") + "».\n"
                + "Por seguridad, nunca compartas tu contraseña por correo.";
        return enviar(correoAnterior, ASUNTO_DESVINCULACION, cuerpo);
    }

    private EstadoAviso enviar(String correo, String asunto, String cuerpo) {
        if (!habilitado) {
            return EstadoAviso.DESHABILITADO;
        }

        SimpleMailMessage mensaje = prepararMensaje(correo, asunto, cuerpo);
        if (mensaje == null) {
            return EstadoAviso.FALLIDO;
        }

        try {
            // No se vuelve a enviar: el servidor de correo pudo aceptar el mensaje antes de informar el error.
            remitenteSmtp.send(mensaje);
            return EstadoAviso.ENVIADO;
        } catch (MailAuthenticationException | MailParseException | MailPreparationException error) {
            return EstadoAviso.FALLIDO;
        } catch (MailSendException error) {
            return contieneRechazoDeConexion(error) ? EstadoAviso.FALLIDO : EstadoAviso.DESCONOCIDO;
        } catch (RuntimeException error) {
            return EstadoAviso.DESCONOCIDO;
        }
    }

    private boolean contieneRechazoDeConexion(Throwable error) {
        for (Throwable causa = error; causa != null; causa = causa.getCause()) {
            if (causa instanceof ConnectException) {
                return true;
            }
        }
        return false;
    }

    private SimpleMailMessage prepararMensaje(String correo, String asunto, String cuerpo) {
        String destinatario = direccionSegura(correo);
        String remitente = direccionSegura(direccionRemitente);
        if (destinatario == null || remitente == null) {
            return null;
        }

        SimpleMailMessage mensaje = new SimpleMailMessage();
        mensaje.setFrom(remitente);
        mensaje.setTo(destinatario);
        mensaje.setSubject(asunto);
        mensaje.setText(cuerpo);
        return mensaje;
    }

    private String direccionSegura(String direccion) {
        if (direccion == null || direccion.isBlank()
                || direccion.indexOf('\r') >= 0 || direccion.indexOf('\n') >= 0) {
            return null;
        }
        return direccion.trim();
    }

    private String textoSeguro(String texto, String alternativa) {
        if (texto == null || texto.isBlank()) {
            return alternativa;
        }
        return texto.replace('\r', ' ').replace('\n', ' ').trim();
    }
}
