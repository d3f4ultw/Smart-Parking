package mx.smartparking.api.operadores;

import java.util.UUID;

/** Contiene el resultado del registro sin mostrar el código de invitación ni sus datos de protección. */
public record RespuestaRegistroOperador(
        UUID id,
        EstadoCuentaOperador estado,
        String estadoInvitacion) {
}
