package mx.smartparking.api.rfid2.servicio;

import java.time.Clock;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.Locale;
import java.util.UUID;
import java.util.function.Predicate;
import java.util.function.LongSupplier;
import java.util.regex.Pattern;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.EstadoConfiguracion;
import mx.smartparking.api.configuracion.ModoHorario;
import mx.smartparking.api.persistencia.RepositorioConfiguracion;
import mx.smartparking.api.rfid2.PlazoEntradaRfid2;
import mx.smartparking.api.rfid2.persistencia.LecturaRfid2ConflictException;
import mx.smartparking.api.rfid2.persistencia.RepositorioRfid2;
import mx.smartparking.api.rfid2.persistencia.ResultadoEntradaRfid2;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

/** Comprueba si una tarjeta puede entrar según la configuración y los datos guardados del estacionamiento. */
@Service
public final class ServicioRfid2 {

    private static final Pattern FORMATO_UID = Pattern.compile("(?i)(?:[0-9a-f]{8}|[0-9a-f]{14}|[0-9a-f]{20})");
    private static final Pattern FORMATO_UUID = Pattern.compile(
            "(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}");

    private final RepositorioRfid2 repositorio;
    private final RepositorioConfiguracion configuracion;
    private final Clock reloj;
    private final LongSupplier relojMonotono;

    @Autowired
    public ServicioRfid2(RepositorioRfid2 repositorio, RepositorioConfiguracion configuracion) {
        this(repositorio, configuracion, Clock.systemUTC());
    }

    ServicioRfid2(RepositorioRfid2 repositorio, RepositorioConfiguracion configuracion, Clock reloj) {
        this(repositorio, configuracion, reloj, System::nanoTime);
    }

    ServicioRfid2(RepositorioRfid2 repositorio, RepositorioConfiguracion configuracion, Clock reloj,
            LongSupplier relojMonotono) {
        this.repositorio = repositorio;
        this.configuracion = configuracion;
        this.reloj = reloj;
        this.relojMonotono = relojMonotono;
    }

    /** Revisa la tarjeta y devuelve la decisión de entrada cuando el resultado ya quedó guardado. */
    public ResultadoEntradaRfid2 registrarEntrada(String uidSolicitado, String lecturaSolicitada) {
        String uid = validarUid(uidSolicitado);
        UUID lecturaId = validarLecturaId(lecturaSolicitada);
        PlazoEntradaRfid2 plazo = new PlazoEntradaRfid2(relojMonotono);
        var actual = configuracion.buscar().orElse(null);
        plazo.milisegundosRestantes();
        if (actual == null || actual.estado() != EstadoConfiguracion.CONFIGURADA || actual.zonaHoraria() == null) {
            throw error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                    "No pudimos confirmar la entrada. Inténtalo más tarde.");
        }
        ZoneId zona;
        try {
            zona = ZoneId.of(actual.zonaHoraria());
        } catch (RuntimeException excepcion) {
            throw error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                    "No pudimos confirmar la entrada. Inténtalo más tarde.");
        }
        Predicate<LocalTime> dentroDeHorario;
        if (actual.modoHorario() == ModoHorario.CONTINUO_24_7) {
            dentroDeHorario = hora -> true;
        } else if (actual.horaApertura().isBefore(actual.horaCierre())) {
            dentroDeHorario = hora -> !hora.isBefore(actual.horaApertura())
                    && hora.isBefore(actual.horaCierre());
        } else {
            dentroDeHorario = hora -> !hora.isBefore(actual.horaApertura())
                    || hora.isBefore(actual.horaCierre());
        }
        try {
            plazo.milisegundosRestantes();
            return repositorio.registrarEntrada(uid, lecturaId, reloj, zona, dentroDeHorario, actual.revision(), plazo);
        } catch (LecturaRfid2ConflictException excepcion) {
            throw error(HttpStatus.CONFLICT, "LECTURA_EN_CONFLICTO", "La lectura no se pudo confirmar.");
        }
    }

    private static String validarUid(String valor) {
        if (valor == null || !FORMATO_UID.matcher(valor).matches()) {
            throw solicitudNoValida();
        }
        return valor.toUpperCase(Locale.ROOT);
    }

    private static UUID validarLecturaId(String valor) {
        if (valor == null || !FORMATO_UUID.matcher(valor).matches()) {
            throw solicitudNoValida();
        }
        try {
            return UUID.fromString(valor);
        } catch (IllegalArgumentException excepcion) {
            throw solicitudNoValida();
        }
    }

    private static ErrorConfiguracion solicitudNoValida() {
        return error(HttpStatus.BAD_REQUEST, "LECTURA_NO_VALIDA", "La lectura enviada no es válida.");
    }

    private static ErrorConfiguracion error(HttpStatus estado, String codigo, String mensaje) {
        return new ErrorConfiguracion(estado, mensaje, codigo);
    }
}
