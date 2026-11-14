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
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;

/** Envía el enlace de invitación sin mostrar ni guardar su código en los registros. */
@Component
public final class AdaptadorInvitacionOperador implements NotificadorRecuperacionOperador {

    private static final String ASUNTO_ACTIVACION = "Activa tu cuenta de Smart Parking";
    private static final String ASUNTO_RECUPERACION = "Crea una nueva contraseña de Smart Parking";

    private final JavaMailSender remitenteSmtp;
    private final boolean habilitado;
    private final String direccionRemitente;

    public AdaptadorInvitacionOperador(
            JavaMailSender remitenteSmtp,
            @Value("${smartparking.correo.habilitado:false}") boolean habilitado,
            @Value("${smartparking.correo.remitente:}") String direccionRemitente) {
        this.remitenteSmtp = remitenteSmtp;
        this.habilitado = habilitado;
        this.direccionRemitente = direccionRemitente;
    }

    @Override
    public boolean estaHabilitado() {
        return habilitado;
    }

    @Override
    public EstadoEnvioInvitacion enviar(String correo, String enlaceActivacion) {
        String cuerpo = "Hola.\n\nAbre este enlace para activar tu cuenta de Smart Parking:\n\n"
                + enlaceActivacion + "\n\n"
                + "El enlace vence dos horas después de su envío y solo puedes usarlo una vez.\n"
                + "No lo compartas con nadie.";
        return enviar(correo, enlaceActivacion, ASUNTO_ACTIVACION, cuerpo);
    }

    @Override
    public EstadoEnvioInvitacion enviarRecuperacion(String correo, String enlaceRecuperacion) {
        String cuerpo = "Hola.\n\nAbre este enlace para crear una nueva contraseña de Smart Parking:\n\n"
                + enlaceRecuperacion + "\n\n"
                + "El enlace vence 30 minutos después de su envío y solo puedes usarlo una vez.\n"
                + "No lo compartas con nadie.";
        return enviar(correo, enlaceRecuperacion, ASUNTO_RECUPERACION, cuerpo);
    }

    private EstadoEnvioInvitacion enviar(String correo, String enlace, String asunto, String cuerpo) {
        if (!habilitado) {
            return EstadoEnvioInvitacion.DESHABILITADO;
        }
        String destinatario = direccionSegura(correo);
        String remitente = direccionSegura(direccionRemitente);
        if (destinatario == null || remitente == null || enlace == null
                || enlace.isBlank() || contieneSalto(enlace)) {
            return EstadoEnvioInvitacion.FALLIDO;
        }

        SimpleMailMessage mensaje = new SimpleMailMessage();
        mensaje.setFrom(remitente);
        mensaje.setTo(destinatario);
        mensaje.setSubject(asunto);
        mensaje.setText(cuerpo);
        try {
            remitenteSmtp.send(mensaje);
            return EstadoEnvioInvitacion.ENVIADO;
        } catch (MailAuthenticationException | MailParseException | MailPreparationException error) {
            return EstadoEnvioInvitacion.FALLIDO;
        } catch (MailSendException error) {
            return contieneRechazoDeConexion(error)
                    ? EstadoEnvioInvitacion.FALLIDO
                    : EstadoEnvioInvitacion.DESCONOCIDO;
        } catch (RuntimeException error) {
            return EstadoEnvioInvitacion.DESCONOCIDO;
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

    private static String direccionSegura(String direccion) {
        if (direccion == null || direccion.isBlank() || contieneSalto(direccion)) {
            return null;
        }
        return direccion.trim();
    }

    private static boolean contieneSalto(String valor) {
        return valor.indexOf('\r') >= 0 || valor.indexOf('\n') >= 0;
    }
}
