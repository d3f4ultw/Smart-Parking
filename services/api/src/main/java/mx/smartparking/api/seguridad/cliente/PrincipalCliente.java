package mx.smartparking.api.seguridad.cliente;

import java.security.Principal;
import java.util.UUID;

/** Reúne la identidad del cliente que inició sesión y la versión vigente de su cuenta. */
public record PrincipalCliente(UUID cuentaId, long revisionAcceso, String correo) implements Principal {

    /** Devuelve el correo de la cuenta en minúsculas y sin espacios al inicio o al final. */
    @Override
    public String getName() {
        return correo;
    }

    @Override
    public String toString() {
        return "PrincipalCliente[cuentaId=" + cuentaId + ", revisionAcceso=" + revisionAcceso
                + ", correo=redactado]";
    }
}
