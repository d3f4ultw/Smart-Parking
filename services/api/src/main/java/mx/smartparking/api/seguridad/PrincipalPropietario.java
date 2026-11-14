package mx.smartparking.api.seguridad;

import java.security.Principal;
import java.util.UUID;

/** Reúne la identidad de la persona que inició sesión y la versión vigente de su acceso. */
public record PrincipalPropietario(
        UUID cuentaId,
        RolCuenta rol,
        long revisionAcceso,
        long revisionPropietario,
        String correo) implements Principal {

    public PrincipalPropietario(long revisionPropietario, String correo) {
        this(new UUID(0, 1), RolCuenta.DUENO, 1, revisionPropietario, correo);
    }

    /** Devuelve el correo como nombre estable de la sesión. */
    @Override
    public String getName() {
        return correo;
    }
}
