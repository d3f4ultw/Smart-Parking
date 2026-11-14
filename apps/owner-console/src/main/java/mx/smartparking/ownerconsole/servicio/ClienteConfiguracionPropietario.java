package mx.smartparking.ownerconsole.servicio;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.net.http.HttpResponse;
import java.util.Map;
import java.util.UUID;
import mx.smartparking.ownerconsole.modelo.DatosPanel;
import mx.smartparking.ownerconsole.modelo.EdicionEstacionamiento;
import mx.smartparking.ownerconsole.modelo.EstadoConfiguracion;

/** Consulta y modifica la configuración inicial y los datos del panel. */
public final class ClienteConfiguracionPropietario {

    private static final String RUTA_ESTADO = "/api/v1/configuracion/estado";
    private final TransporteHttpPropietario transporte;

    ClienteConfiguracionPropietario(TransporteHttpPropietario transporte) {
        this.transporte = transporte;
    }

    public EstadoConfiguracion consultarEstado() {
        JsonNode respuesta = transporte.enviar("GET", RUTA_ESTADO, null, Map.of(), false);
        return EstadoConfiguracion.desde(transporte.texto(respuesta, "estado"));
    }

    public DatosPanel consultarPanel() {
        HttpResponse<String> respuesta = transporte.solicitar("GET", "/api/v1/panel", null, Map.of(), false);
        return convertirPanel(transporte.parsear(respuesta.body(), false), respuesta, false);
    }

    /**
     * solicita el cambio de nombre del estacionamiento
     * envía información para detectar otros cambios y un identificador nuevo para la solicitud
     */
    public DatosPanel renombrarEstacionamiento(String nombre, DatosPanel actual) {
        ObjectNode cuerpo = transporte.nuevoObjetoJson();
        cuerpo.put("nombre", nombre);
        HttpResponse<String> respuesta = transporte.solicitarConCsrf(
                "PATCH",
                "/api/v1/estacionamiento",
                cuerpo.toString(),
                Map.of(
                        "If-Match", actual.etag(),
                        "Idempotency-Key", UUID.randomUUID().toString()),
                true);
        return convertirPanel(transporte.parsear(respuesta.body(), true), respuesta, true);
    }

    /**
     * solicita el cambio de tipo y horario del estacionamiento
     * envía información para detectar otros cambios y un identificador nuevo para la solicitud
     */
    public DatosPanel actualizarDatosEstacionamiento(EdicionEstacionamiento edicion, DatosPanel actual) {
        ObjectNode cuerpo = transporte.nuevoObjetoJson();
        cuerpo.put("tipo", edicion.tipo());
        ObjectNode horario = cuerpo.putObject("horario");
        horario.put("modo", edicion.modoHorario());
        horario.put("zonaHoraria", edicion.zonaHoraria());
        if (edicion.horaApertura() == null) {
            horario.putNull("horaApertura");
        } else {
            horario.put("horaApertura", edicion.horaApertura());
        }
        if (edicion.horaCierre() == null) {
            horario.putNull("horaCierre");
        } else {
            horario.put("horaCierre", edicion.horaCierre());
        }
        HttpResponse<String> respuesta = transporte.solicitarConCsrf(
                "PATCH",
                "/api/v1/estacionamiento/datos",
                cuerpo.toString(),
                Map.of(
                        "If-Match", actual.etag(),
                        "Idempotency-Key", UUID.randomUUID().toString()),
                true);
        return convertirPanel(transporte.parsear(respuesta.body(), true), respuesta, true);
    }

    /**
     * envía todos los datos necesarios para la configuración inicial
     * incluye el identificador recibido para reconocer la solicitud
     */
    public ResultadoTransicion registrar(PayloadConfiguracion payload, String claveIdempotencia) {
        JsonNode respuesta = transporte.enviarConCsrf(
                "POST",
                "/api/v1/configuracion/inicial",
                payload.json(),
                Map.of("Idempotency-Key", claveIdempotencia),
                true);
        return new ResultadoTransicion(
                transporte.texto(respuesta, "estado", true),
                transporte.textoOpcional(respuesta, "avisoBienvenida"));
    }

    private DatosPanel convertirPanel(
            JsonNode raiz,
            HttpResponse<String> respuesta,
            boolean resultadoIncierto) {
        JsonNode propietario = raiz.path("propietario");
        JsonNode estacionamiento = raiz.path("estacionamiento");
        JsonNode horario = estacionamiento.path("horario");
        long revision = raiz.path("revision").asLong();
        String etag = respuesta.headers().firstValue("ETag")
                .orElseGet(() -> "\"" + revision + "\"");
        return new DatosPanel(
                revision,
                raiz.path("revisionPropietario").asLong(),
                new DatosPanel.Propietario(
                        transporte.texto(propietario, "nombres", resultadoIncierto),
                        transporte.texto(
                                propietario,
                                propiedadDisponible(propietario, "primerApellido", "apellidoPaterno"),
                                resultadoIncierto),
                        transporte.textoOpcional(
                                propietario,
                                propiedadDisponible(propietario, "segundoApellido", "apellidoMaterno")),
                        transporte.texto(propietario, "correo", resultadoIncierto)),
                new DatosPanel.Estacionamiento(
                        transporte.texto(estacionamiento, "id", resultadoIncierto),
                        transporte.texto(estacionamiento, "nombre", resultadoIncierto),
                        transporte.texto(estacionamiento, "tipo", resultadoIncierto),
                        new DatosPanel.Horario(
                                transporte.texto(horario, "modo", resultadoIncierto),
                                transporte.texto(horario, "zonaHoraria", resultadoIncierto),
                                transporte.textoOpcional(horario, "horaApertura"),
                                transporte.textoOpcional(horario, "horaCierre"))),
                etag);
    }

    private static String propiedadDisponible(JsonNode objeto, String nombreCanonico, String aliasAnterior) {
        return objeto.has(nombreCanonico) ? nombreCanonico : aliasAnterior;
    }
}
