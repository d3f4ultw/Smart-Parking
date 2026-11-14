package mx.smartparking.ownerconsole.servicio;

import java.util.Objects;

/** Encapsula el JSON contractual sin exponer contraseñas al convertirlo a texto. */
public final class PayloadConfiguracion {

    private final String json;

    public PayloadConfiguracion(String json) {
        this.json = Objects.requireNonNull(json);
    }

    public String json() {
        return json;
    }
}
