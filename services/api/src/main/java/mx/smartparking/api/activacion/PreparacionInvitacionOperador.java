package mx.smartparking.api.activacion;

import java.time.Instant;
import java.util.UUID;

/**
 * Conserva por un momento los datos necesarios para enviar la primera invitación sin mostrar
 * al solicitante el código del enlace.
 */
public final class PreparacionInvitacionOperador {

    private final UUID operadorId;
    private final String correo;
    private final String token;
    private final String tokenHash;
    private final Instant venceEn;
    private final String origen;
    private final String operacion;
    private final String claveHash;

    PreparacionInvitacionOperador(
            UUID operadorId, String correo, String token, String tokenHash, Instant venceEn, String origen) {
        this(operadorId, correo, token, tokenHash, venceEn, origen, null, null);
    }

    PreparacionInvitacionOperador(
            UUID operadorId, String correo, String token, String tokenHash,
            Instant venceEn, String origen, String operacion, String claveHash) {
        this.operadorId = operadorId;
        this.correo = correo;
        this.token = token;
        this.tokenHash = tokenHash;
        this.venceEn = venceEn;
        this.origen = origen;
        this.operacion = operacion;
        this.claveHash = claveHash;
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

    Instant venceEn() {
        return venceEn;
    }

    String origen() {
        return origen;
    }

    String operacion() {
        return operacion;
    }

    String claveHash() {
        return claveHash;
    }

    @Override
    public String toString() {
        return "PreparacionInvitacionOperador[datos=[REDACTADOS]]";
    }
}
