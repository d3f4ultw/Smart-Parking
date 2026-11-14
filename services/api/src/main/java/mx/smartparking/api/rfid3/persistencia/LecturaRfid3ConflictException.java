package mx.smartparking.api.rfid3.persistencia;

/** Avisa que la salida ya confirmada corresponde a una tarjeta distinta. */
public final class LecturaRfid3ConflictException extends RuntimeException {

    public LecturaRfid3ConflictException() {
        super("La lectura ya fue utilizada con otra tarjeta.");
    }
}
