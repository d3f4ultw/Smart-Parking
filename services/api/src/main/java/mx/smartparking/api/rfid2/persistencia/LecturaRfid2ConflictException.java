package mx.smartparking.api.rfid2.persistencia;

/** Indica que el identificador de una lectura ya se usó para otra tarjeta o solicitud. */
public final class LecturaRfid2ConflictException extends RuntimeException {

    public LecturaRfid2ConflictException() {
        super("La lectura ya fue utilizada con otra tarjeta.");
    }
}
