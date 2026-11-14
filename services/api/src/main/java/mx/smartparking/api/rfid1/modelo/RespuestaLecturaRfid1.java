package mx.smartparking.api.rfid1.modelo;

/** Indica el avance y el resultado de la lectura sin mostrar el número de la tarjeta. */
public record RespuestaLecturaRfid1(String capturaId, String estado, String resultado) {
}
