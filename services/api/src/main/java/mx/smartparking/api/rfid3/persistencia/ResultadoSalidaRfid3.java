package mx.smartparking.api.rfid3.persistencia;

/** Reúne la decisión guardada y el motivo de una lectura en la salida. */
public record ResultadoSalidaRfid3(String resultado, String motivo) {

    public static ResultadoSalidaRfid3 autorizada() {
        return new ResultadoSalidaRfid3("AUTORIZADA", null);
    }

    public static ResultadoSalidaRfid3 denegada(String motivo) {
        return new ResultadoSalidaRfid3("DENEGADA", motivo);
    }
}
