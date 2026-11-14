package mx.smartparking.api.seguridad;

import java.util.UUID;

/** Reúne los datos necesarios para comprobar el acceso de un propietario u operador autorizado. */
public record CredencialesPropietario(
        UUID cuentaId,
        RolCuenta rol,
        long revisionAcceso,
        long revisionPropietario,
        String correo,
        String hashContrasenaAcceso) {

    public CredencialesPropietario(long revisionPropietario, String correo, String hashContrasenaAcceso) {
        this(new UUID(0, 1), RolCuenta.DUENO, 1, revisionPropietario, correo, hashContrasenaAcceso);
    }
}
