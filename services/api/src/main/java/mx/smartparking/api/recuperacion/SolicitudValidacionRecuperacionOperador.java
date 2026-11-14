package mx.smartparking.api.recuperacion;

/** Contiene el código recibido del enlace para comprobar si puede usarse. */
public record SolicitudValidacionRecuperacionOperador(String token) {

    @Override
    public String toString() {
        return "SolicitudValidacionRecuperacionOperador[datos=[REDACTADOS]]";
    }
}
