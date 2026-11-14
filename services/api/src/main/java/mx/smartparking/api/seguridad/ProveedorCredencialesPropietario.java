package mx.smartparking.api.seguridad;

import java.util.Optional;

/** Busca los datos necesarios para permitir la entrada a un propietario u operador autorizado. */
public interface ProveedorCredencialesPropietario {

    /**
     * Busca una cuenta autorizada usando el correo escrito en minúsculas y sin espacios
     * al principio o al final.
     *
     * @param correoNormalizado correo de la persona que desea entrar
     * @return datos de acceso o un resultado vacío si no se encuentra una cuenta autorizada
     */
    Optional<CredencialesPropietario> buscarPorCorreo(String correoNormalizado);
}
