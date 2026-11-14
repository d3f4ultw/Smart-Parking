package mx.smartparking.api.eventos;

import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.http.HttpStatus;

/** Comprueba que la persona que recibe avisos mantenga una sesión administrativa válida. */
final class ValidadorSesionAdministracion {

    private final GestorSesionesPropietario gestorSesiones;
    private final RepositorioCuentas repositorioCuentas;

    ValidadorSesionAdministracion(
            GestorSesionesPropietario gestorSesiones,
            RepositorioCuentas repositorioCuentas) {
        this.gestorSesiones = gestorSesiones;
        this.repositorioCuentas = repositorioCuentas;
    }

    boolean esVigente(String idSesion, PrincipalPropietario principal) {
        if (idSesion == null || !esRolAdministrativo(principal)) {
            return false;
        }
        try {
            return gestorSesiones.estaRegistrada(idSesion, principal)
                    && repositorioCuentas.sesionVigente(
                            principal.cuentaId(),
                            principal.revisionAcceso(),
                            principal.rol().name(),
                            principal.revisionPropietario());
        } catch (RuntimeException excepcion) {
            return false;
        }
    }

    void exigirPropietario(PrincipalPropietario principal) {
        if (!esRolAdministrativo(principal)) {
            throw new ErrorConfiguracion(
                    HttpStatus.FORBIDDEN, "No tienes acceso para ver esta información.", "PERMISO_INSUFICIENTE");
        }
    }

    private static boolean esRolAdministrativo(PrincipalPropietario principal) {
        return principal != null
                && (principal.rol() == RolCuenta.DUENO || principal.rol() == RolCuenta.OPERADOR);
    }
}
