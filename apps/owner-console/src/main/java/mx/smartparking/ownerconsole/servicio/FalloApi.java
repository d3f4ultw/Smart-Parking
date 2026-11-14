package mx.smartparking.ownerconsole.servicio;

/** Fallo HTTP */
public final class FalloApi extends RuntimeException {

    private final int estadoHttp;
    private final boolean respuestaIncierta;

    public FalloApi(int estadoHttp, boolean respuestaIncierta, String mensaje) {
        super(mensaje, null, false, false);
        this.estadoHttp = estadoHttp;
        this.respuestaIncierta = respuestaIncierta;
    }

    public int estadoHttp() {
        return estadoHttp;
    }

    public boolean respuestaIncierta() {
        return respuestaIncierta;
    }
}
