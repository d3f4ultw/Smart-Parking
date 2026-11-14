package mx.smartparking.api.operadores;

import java.util.UUID;

/** Reúne los datos que se pueden mostrar de una cuenta y el estado de su invitación. */
public record Operador(
        UUID id,
        String nombres,
        String primerApellido,
        String segundoApellido,
        String correo,
        EstadoCuentaOperador estado,
        String estadoInvitacion,
        boolean puedeReemitirInvitacion,
        String empleadoIdTexto,
        String estadoConciliacion) {

    public Operador(
            UUID id,
            String nombres,
            String primerApellido,
            String segundoApellido,
            String correo,
            EstadoCuentaOperador estado,
            String estadoInvitacion,
            boolean puedeReemitirInvitacion) {
        this(id, nombres, primerApellido, segundoApellido, correo, estado,
                estadoInvitacion, puedeReemitirInvitacion, null, "LEGADO_SIN_VINCULO");
    }
}
