package mx.smartparking.api.rfid2.persistencia;

/** Reúne la decisión guardada y el motivo de una lectura en la entrada. */
public record ResultadoEntradaRfid2(String resultado, String motivo) {

    public static ResultadoEntradaRfid2 autorizada() {
        return new ResultadoEntradaRfid2("AUTORIZADA", null);
    }

    public static ResultadoEntradaRfid2 denegada(String motivo) {
        return new ResultadoEntradaRfid2("DENEGADA", motivo);
    }
}
