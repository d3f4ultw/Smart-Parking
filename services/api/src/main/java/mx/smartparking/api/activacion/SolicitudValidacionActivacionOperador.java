package mx.smartparking.api.activacion;

/** Recibe el código del enlace de activación, que no debe aparecer en los registros. */
public record SolicitudValidacionActivacionOperador(String token) {

    @Override
    public String toString() {
        return "SolicitudValidacionActivacionOperador[token=[REDACTADO]]";
    }
}
