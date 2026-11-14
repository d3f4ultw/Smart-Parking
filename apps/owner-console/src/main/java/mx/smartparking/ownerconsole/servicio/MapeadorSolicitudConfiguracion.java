package mx.smartparking.ownerconsole.servicio;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.Arrays;
import mx.smartparking.ownerconsole.modelo.BorradorConfiguracion;

/** prepara la información para registrar al primer propietario o completar un cambio de propietario. */
public final class MapeadorSolicitudConfiguracion {

    private final ObjectMapper json = new ObjectMapper();

    /**
     * prepara los datos escritos en el formato que necesita el servidor
     * limpia las copias de contraseñas usadas para prepararlos sin cambiar las originales
     */
    public PayloadConfiguracion mapear(BorradorConfiguracion borrador) {
        char[] contrasenaAcceso = borrador.copiarContrasenaAcceso();
        char[] contrasenaAdministrativa = borrador.copiarContrasenaAdministrativa();
        try {
            ObjectNode raiz = json.createObjectNode();
            ObjectNode propietario = raiz.putObject("propietario");
            propietario.put("nombres", borrador.nombres());
            propietario.put("primerApellido", borrador.primerApellido());
            if (borrador.segundoApellido() == null || borrador.segundoApellido().isBlank()) {
                propietario.putNull("segundoApellido");
            } else {
                propietario.put("segundoApellido", borrador.segundoApellido());
            }
            propietario.put("correo", borrador.correo());
            propietario.put("contrasenaAcceso", new String(contrasenaAcceso));
            propietario.put("contrasenaAdministrativa", new String(contrasenaAdministrativa));

            ObjectNode estacionamiento = raiz.putObject("estacionamiento");
            estacionamiento.put("nombre", borrador.nombreEstacionamiento());
            estacionamiento.put("tipo", borrador.tipoEstacionamiento());
            ObjectNode horario = estacionamiento.putObject("horario");
            horario.put("modo", borrador.modoHorario());
            horario.put("zonaHoraria", borrador.zonaHoraria());
            if ("INTERVALO_DIARIO".equals(borrador.modoHorario())) {
                horario.put("horaApertura", borrador.horaApertura());
                horario.put("horaCierre", borrador.horaCierre());
            } else {
                horario.putNull("horaApertura");
                horario.putNull("horaCierre");
            }
            return new PayloadConfiguracion(raiz.toString());
        } finally {
            Arrays.fill(contrasenaAcceso, '\0');
            Arrays.fill(contrasenaAdministrativa, '\0');
        }
    }
}
