package mx.smartparking.api.transferencia;

/** Contiene la contraseña administrativa que se usa para recuperar el permiso de cambio de propietario. */
public record SolicitudRecuperacion(String contrasenaAdministrativa) {

    @Override
    public String toString() {
        return "SolicitudRecuperacion[contrasenaAdministrativa=[REDACTADA]]";
    }
}
