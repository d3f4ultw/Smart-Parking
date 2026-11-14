package mx.smartparking.api.persistencia.membresia;

import java.time.Instant;
import java.util.UUID;

/** Guarda el estado de un intento de pago para reconocerlo si el cliente repite su solicitud. */
public record IntentoCheckoutPersistido(
        UUID intentoId,
        UUID clienteId,
        EstadoCheckoutPersistido estado,
        String sessionId,
        String priceId,
        Instant expiraEn,
        Instant creadoEn) {
}
