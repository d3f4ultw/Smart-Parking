package mx.smartparking.api.persistencia;

import java.util.UUID;
import mx.smartparking.api.seguridad.RolCuenta;

/** Reúne los datos necesarios de una cuenta para completar su activación sin cambios simultáneos. */
public record CuentaActivacionOperador(
        UUID operadorId,
        RolCuenta rol,
        String estado,
        String correo,
        String hashContrasena,
        long revisionAcceso,
        Long empleadoId) {

    public CuentaActivacionOperador(
            UUID operadorId, RolCuenta rol, String estado, String correo,
            String hashContrasena, long revisionAcceso) {
        this(operadorId, rol, estado, correo, hashContrasena, revisionAcceso, null);
    }
}
