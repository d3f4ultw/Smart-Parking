package mx.smartparking.api.rfid1.servicio;

import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;

/** Determina qué versión del acceso se guarda junto con una lectura de tarjeta. */
final class RevisionCapturaRfid1 {

    private static final long MARCADOR_OPERADOR = 1L;

    private RevisionCapturaRfid1() {
    }

    /**
     * Conserva la versión de acceso del propietario; para un operador guarda un valor positivo porque
     * no usa esa misma versión.
     */
    static long persistida(PrincipalPropietario principal) {
        return principal.rol() == RolCuenta.OPERADOR
                ? MARCADOR_OPERADOR
                : principal.revisionPropietario();
    }
}
