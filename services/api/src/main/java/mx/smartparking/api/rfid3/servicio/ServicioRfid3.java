package mx.smartparking.api.rfid3.servicio;

import java.util.Locale;
import java.util.UUID;
import java.util.regex.Pattern;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.rfid3.persistencia.LecturaRfid3ConflictException;
import mx.smartparking.api.rfid3.persistencia.RepositorioRfid3;
import mx.smartparking.api.rfid3.persistencia.ResultadoSalidaRfid3;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

/** Revisa la tarjeta de salida y espera a que se guarde la decisión correspondiente. */
@Service
public final class ServicioRfid3 {

    private static final Pattern FORMATO_UID = Pattern.compile("(?i)(?:[0-9a-f]{8}|[0-9a-f]{14}|[0-9a-f]{20})");
    private static final Pattern FORMATO_UUID = Pattern.compile(
            "(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}");

    private final RepositorioRfid3 repositorio;

    public ServicioRfid3(RepositorioRfid3 repositorio) {
        this.repositorio = repositorio;
    }

    /** Devuelve la decisión una vez que se confirmó o rechazó el registro de salida. */
    public ResultadoSalidaRfid3 registrarSalida(String uidSolicitado, String lecturaSolicitada) {
        String uid = validarUid(uidSolicitado);
        UUID lecturaId = validarLecturaId(lecturaSolicitada);
        try {
            return repositorio.registrarSalida(uid, lecturaId);
        } catch (LecturaRfid3ConflictException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                    "La lectura no se pudo confirmar.", "LECTURA_EN_CONFLICTO");
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
        return new ErrorConfiguracion(HttpStatus.BAD_REQUEST, "La lectura enviada no es válida.", "LECTURA_NO_VALIDA");
    }
}
