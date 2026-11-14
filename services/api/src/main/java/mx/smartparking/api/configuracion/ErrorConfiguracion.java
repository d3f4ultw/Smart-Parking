package mx.smartparking.api.configuracion;

import org.springframework.http.HttpStatus;

/** Reúne un error de la operación y el estado que se enviará a quien hizo la solicitud. */
public final class ErrorConfiguracion extends RuntimeException {

    private final HttpStatus estadoHttp;
    private final String codigo;

    public ErrorConfiguracion(HttpStatus estadoHttp, String mensaje) {
        this(estadoHttp, mensaje, null);
    }

    public ErrorConfiguracion(HttpStatus estadoHttp, String mensaje, String codigo) {
        super(mensaje);
        this.estadoHttp = estadoHttp;
        this.codigo = codigo;
    }

    public HttpStatus estadoHttp() {
        return estadoHttp;
    }

    public String codigo() {
        return codigo;
    }
}
