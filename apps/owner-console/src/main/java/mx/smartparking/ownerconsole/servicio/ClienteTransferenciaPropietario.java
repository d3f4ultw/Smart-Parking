package mx.smartparking.ownerconsole.servicio;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.Map;
import mx.smartparking.ownerconsole.modelo.DatosPanel;
import mx.smartparking.ownerconsole.modelo.EstadoConfiguracion;

/** Opera inicio, recuperación y finalización del reemplazo de propietario. */
public final class ClienteTransferenciaPropietario {

    private final TransporteHttpPropietario transporte;

    ClienteTransferenciaPropietario(TransporteHttpPropietario transporte) {
        this.transporte = transporte;
    }

    /**
     * solicita iniciar el cambio de propietario con la contraseña de administración
     * envía información sobre el estado actual y un identificador para reconocer la solicitud
     */
    public ResultadoTransicion iniciarTransferencia(
            String contrasenaAdministrativa,
            DatosPanel panel,
            String claveIdempotencia) {
        ObjectNode cuerpo = transporte.nuevoObjetoJson();
        cuerpo.put("contrasenaAdministrativa", contrasenaAdministrativa);
        JsonNode respuesta = transporte.enviarConCsrf(
                "POST",
                "/api/v1/transferencia/iniciar",
                cuerpo.toString(),
                Map.of("If-Match", panel.etag(), "Idempotency-Key", claveIdempotencia),
                true);
        return crearResultadoTransferencia(respuesta, transporte.textoOpcional(respuesta, "avisoTransferencia"));
    }

    /**
     * solicita recuperar el cambio con la contraseña de administración anterior
     * la autorización recibida permite continuar con el cambio de propietario
     */
    public ResultadoTransicion recuperarTransferencia(String contrasenaAdministrativa) {
        ObjectNode cuerpo = transporte.nuevoObjetoJson();
        cuerpo.put("contrasenaAdministrativa", contrasenaAdministrativa);
        JsonNode respuesta = transporte.enviarConCsrf(
                "POST",
                "/api/v1/transferencia/recuperar",
                cuerpo.toString(),
                Map.of(),
                true);
        return crearResultadoTransferencia(respuesta, "");
    }

    /**
     * envía todos los datos necesarios para terminar el cambio de propietario
     * incluye la autorización para continuar y un identificador de la solicitud
     */
    public ResultadoTransicion completarTransferencia(
            PayloadConfiguracion payload,
            String grant,
            String claveIdempotencia) {
        JsonNode respuesta = transporte.enviarConCsrf(
                "POST",
                "/api/v1/transferencia/completar",
                payload.json(),
                Map.of("X-Transfer-Grant", grant, "Idempotency-Key", claveIdempotencia),
                true);
        return new ResultadoTransicion(
                transporte.texto(respuesta, "estado", true),
                transporte.textoOpcional(respuesta, "avisoBienvenida"));
    }

    private ResultadoTransicion crearResultadoTransferencia(JsonNode respuesta, String avisoCorreo) {
        String estado = transporte.texto(respuesta, "estado", true);
        String transferenciaId = transporte.texto(respuesta, "transferenciaId", true);
        String grant = transporte.texto(respuesta, "grant", true);
        if (!EstadoConfiguracion.TRANSFERENCIA_PENDIENTE.name().equals(estado)
                || transferenciaId.isBlank()
                || grant.isBlank()) {
            throw new FalloApi(0, true, "No pudimos iniciar el cambio de propietario. Inténtalo de nuevo.");
        }
        return new ResultadoTransicion(
                estado, avisoCorreo, transferenciaId, grant, transporte.textoOpcional(respuesta, "venceEn"));
    }
}
