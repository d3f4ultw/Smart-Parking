package mx.smartparking.api.rfid2.persistencia;

import java.time.Clock;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.UUID;
import java.util.function.Predicate;
import mx.smartparking.api.rfid2.PlazoEntradaRfid2;

/** Define cómo guardar la decisión y el registro de una entrada por tarjeta. */
public interface RepositorioRfid2 {

    ResultadoEntradaRfid2 registrarEntrada(
            String uid, UUID lecturaId, Clock reloj, ZoneId zonaHoraria, Predicate<LocalTime> dentroDeHorario,
            long revisionConfiguracion, PlazoEntradaRfid2 plazo);
}
