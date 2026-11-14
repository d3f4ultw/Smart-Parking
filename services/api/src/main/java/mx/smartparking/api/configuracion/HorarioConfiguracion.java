package mx.smartparking.api.configuracion;

import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeFormatterBuilder;
import java.time.format.ResolverStyle;
import java.util.Set;

/** Reúne la hora de apertura, la de cierre y la zona horaria elegidas por el propietario. */
public record HorarioConfiguracion(
        ModoHorario modo,
        String zonaHoraria,
        LocalTime horaApertura,
        LocalTime horaCierre) {

    private static final DateTimeFormatter FORMATO_HORA = new DateTimeFormatterBuilder()
            .appendPattern("HH:mm")
            .toFormatter()
            .withResolverStyle(ResolverStyle.STRICT);
    private static final Set<String> ZONAS_IANA = ZoneId.getAvailableZoneIds();

    public HorarioConfiguracion {
        if (modo == null) {
            throw new IllegalArgumentException("Selecciona el modo del horario.");
        }
        if (zonaHoraria == null || !ZONAS_IANA.contains(zonaHoraria)) {
            throw new IllegalArgumentException("Selecciona una zona horaria válida.");
        }
        ZoneId zona = ZoneId.of(zonaHoraria);
        if (zona instanceof ZoneOffset) {
            throw new IllegalArgumentException("Selecciona una zona horaria válida.");
        }
        if (modo == ModoHorario.CONTINUO_24_7) {
            if (horaApertura != null || horaCierre != null) {
                throw new IllegalArgumentException("Para abrir todo el día, deja vacías las horas de apertura y cierre.");
            }
        } else if (horaApertura == null || horaCierre == null || horaApertura.equals(horaCierre)) {
            throw new IllegalArgumentException("Indica horas de apertura y cierre distintas.");
        }
    }

    /** Interpreta horas y minutos, por ejemplo 09:30; no acepta 24:00 ni segundos. */
    public static LocalTime parsearHora(String valor, String campo) {
        if (valor == null) {
            throw new IllegalArgumentException("Indica la hora de " + campo + ".");
        }
        try {
            return LocalTime.parse(valor, FORMATO_HORA);
        } catch (RuntimeException excepcion) {
            throw new IllegalArgumentException("Escribe una hora válida para " + campo + ".");
        }
    }
}
