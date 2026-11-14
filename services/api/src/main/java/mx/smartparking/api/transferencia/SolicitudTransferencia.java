package mx.smartparking.api.transferencia;

/** Contiene la contraseña administrativa que confirma el retiro del acceso del propietario actual. */
public record SolicitudTransferencia(String contrasenaAdministrativa) {

    @Override
    public String toString() {
        return "SolicitudTransferencia[contrasenaAdministrativa=[REDACTADA]]";
    }
}
