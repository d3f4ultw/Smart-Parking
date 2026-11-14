package mx.smartparking.api.operadores;

import java.time.Instant;
import java.util.UUID;

/** Reúne los datos guardados de una cuenta de operador para consultar o cambiar su estado. */
public record CuentaOperadorAdministrable(
        UUID id,
        String nombres,
        String primerApellido,
        String segundoApellido,
        String correo,
        EstadoCuentaOperador estado,
        Instant creadaEn,
        long revisionAcceso,
        Long empleadoId) {

    public CuentaOperadorAdministrable(
            UUID id,
            String nombres,
            String primerApellido,
            String segundoApellido,
            String correo,
            EstadoCuentaOperador estado,
            Instant creadaEn,
            long revisionAcceso) {
        this(id, nombres, primerApellido, segundoApellido, correo, estado, creadaEn, revisionAcceso, null);
    }
}
