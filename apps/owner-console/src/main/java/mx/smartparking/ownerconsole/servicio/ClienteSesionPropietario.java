package mx.smartparking.ownerconsole.servicio;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.Map;
import mx.smartparking.ownerconsole.modelo.SesionPropietario;

/** Coordina el acceso, la consulta y el cierre de la sesión del propietario. */
public final class ClienteSesionPropietario {

    private final TransporteHttpPropietario transporte;

    ClienteSesionPropietario(TransporteHttpPropietario transporte) {
        this.transporte = transporte;
    }

    /**
     * pregunta al servidor si el propietario tiene una sesión abierta
     * actualiza el token de protección recibido incluso si no hay una sesión abierta
     */
    public SesionPropietario consultarSesion() {
        JsonNode respuesta = transporte.enviar("GET", "/api/v1/sesion", null, Map.of(), false);
        transporte.actualizarTokenCsrf(transporte.textoOpcional(respuesta, "csrfToken"));
        return interpretarSesion(respuesta);
    }

    /**
     * envía el correo y la contraseña para iniciar una sesión protegida
     * actualiza el token de protección con la respuesta del servidor
     */
    public SesionPropietario iniciarSesion(String correo, String contrasena) {
        ObjectNode cuerpo = transporte.nuevoObjetoJson();
        cuerpo.put("correo", correo);
        cuerpo.put("contrasena", contrasena);
        JsonNode respuesta = transporte.enviarConCsrf(
                "POST", "/api/v1/sesion", cuerpo.toString(), Map.of(), false);
        transporte.actualizarTokenCsrf(transporte.textoOpcional(respuesta, "csrfToken"));
        return interpretarSesion(respuesta);
    }

    private SesionPropietario interpretarSesion(JsonNode respuesta) {
        JsonNode autenticada = respuesta.path("autenticada");
        JsonNode rol = respuesta.path("rol");
        JsonNode correo = respuesta.path("correo");
        JsonNode revision = respuesta.path("revisionPropietario");
        if (!autenticada.isBoolean() || !autenticada.booleanValue()
                || !rol.isTextual() || !"DUENO".equals(rol.textValue())
                || !correo.isTextual() || correo.textValue().isBlank()
                || !revision.isIntegralNumber() || !revision.canConvertToLong()
                || revision.longValue() < 0) {
            return new SesionPropietario(false, "", 0);
        }
        return new SesionPropietario(true, correo.textValue(), revision.longValue());
    }

    /**
     * solicita cerrar la sesión usando el token de protección
     * al cerrarla borra el token y también puede descartarlo si la solicitud falla
     */
    public void cerrarSesion() {
        transporte.enviarConCsrf("DELETE", "/api/v1/sesion", null, Map.of(), false);
        transporte.limpiarTokenCsrf();
    }
}
