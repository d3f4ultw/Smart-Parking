package mx.smartparking.api.operadores;

import java.util.UUID;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;
import mx.smartparking.api.activacion.PreparacionInvitacionOperador;

/** Define cómo la administración de cuentas prepara invitaciones y enlaces de recuperación. */
public interface PuertoInvitacionesAdministracion {

    /**
     * Consulta qué acciones están disponibles sin mostrar los códigos de los enlaces ni sus datos de
     * protección.
     */
    ProyeccionInvitacionOperador consultar(UUID operadorId);

    /**
     * Reconoce una reactivación ya realizada cuando se repite la misma solicitud con datos de una
     * versión anterior.
     */
    boolean reactivacionRepetida(UUID operadorId, String rawIdempotencyKey);

    /** Prepara una invitación mientras se guarda la reactivación de la cuenta. */
    PreparacionInvitacionOperador prepararReactivacion(
            UUID operadorId, String correo, String rawIdempotencyKey);

    /** Sustituye la invitación pendiente al cambiar el correo del operador. */
    PreparacionInvitacionOperador prepararCambioCorreo(
            UUID operadorId, String correo, String rawIdempotencyKey);

    /** Intenta enviar una invitación después de guardar el nuevo correo del operador. */
    EstadoEnvioInvitacion enviarCambioCorreo(PreparacionInvitacionOperador preparacion);

    /** Deja sin efecto las invitaciones y los enlaces de recuperación que aún no se han usado. */
    void invalidarPendientes(UUID operadorId);

    /** Intenta enviar una sola invitación después de guardar la reactivación y registra el resultado. */
    EstadoEnvioInvitacion enviarReactivacion(PreparacionInvitacionOperador preparacion);
}
