package mx.smartparking.ownerconsole.servicio;

/** Resultado de una mutación; omite grant y otros datos al representarse como texto. */
public final class ResultadoTransicion {

    private final String estado;
    private final String avisoCorreo;
    private final String transferenciaId;
    private final String grant;
    private final String venceEn;

    public ResultadoTransicion(
            String estado,
            String avisoCorreo,
            String transferenciaId,
            String grant,
            String venceEn) {
        this.estado = estado;
        this.avisoCorreo = avisoCorreo;
        this.transferenciaId = transferenciaId;
        this.grant = grant;
        this.venceEn = venceEn;
    }

    public ResultadoTransicion(String estado, String avisoCorreo) {
        this(estado, avisoCorreo, null, null, null);
    }

    public String estado() {
        return estado;
    }

    public String avisoCorreo() {
        return avisoCorreo;
    }

    public String transferenciaId() {
        return transferenciaId;
    }

    public String grant() {
        return grant;
    }

    public String venceEn() {
        return venceEn;
    }
}
