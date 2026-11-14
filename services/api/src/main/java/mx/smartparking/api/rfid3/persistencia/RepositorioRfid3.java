package mx.smartparking.api.rfid3.persistencia;

import java.util.UUID;

/** Define cómo guardar el fin de una visita cuando se lee la tarjeta de salida. */
public interface RepositorioRfid3 {

    ResultadoSalidaRfid3 registrarSalida(String uid, UUID lecturaId);
}
