package mx.smartparking.api.recuperacion;

import java.time.Instant;
import java.util.UUID;

/**
 * Conserva por un momento los datos para enviar el correo sin guardar ni mostrar al propietario el
 * código del enlace.
 */
public final class PreparacionRecuperacionOperador {

    private final UUID operadorId;
    private final String correo;
    private final String token;
    private final String tokenHash;
    private final String claveHash;
    private final Instant venceEn;
    private final String origen;

    PreparacionRecuperacionOperador(
            UUID operadorId, String correo, String token, String tokenHash,
            String claveHash, Instant venceEn, String origen) {
        this.operadorId = operadorId;
        this.correo = correo;
        this.token = token;
        this.tokenHash = tokenHash;
        this.claveHash = claveHash;
        this.venceEn = venceEn;
        this.origen = origen;
    }

    UUID operadorId() {
        return operadorId;
    }

    String correo() {
        return correo;
    }

    String token() {
        return token;
    }

    String tokenHash() {
        return tokenHash;
    }

    String claveHash() {
        return claveHash;
    }

    Instant venceEn() {
        return venceEn;
    }

    String origen() {
        return origen;
    }

    @Override
    public String toString() {
        return "PreparacionRecuperacionOperador[datos=[REDACTADOS]]";
    }
}
