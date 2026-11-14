package mx.smartparking.api.configuracion;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.UUID;

/**
 * Reúne los datos del propietario y del estacionamiento que se muestran en su panel sin incluir
 * contraseñas ni permisos de cambio de propietario.
 */
public record PanelPropietario(
        long revision,
        long revisionPropietario,
        PropietarioPanel propietario,
        EstacionamientoPanel estacionamiento) {

    public record PropietarioPanel(
            String nombres,
            String primerApellido,
            String segundoApellido,
            String correo) {

        /** También muestra el primer apellido con el nombre anterior para aplicaciones que aún lo utilizan. */
        @JsonProperty(value = "apellidoPaterno", access = JsonProperty.Access.READ_ONLY)
        public String aliasPrimerApellido() {
            return primerApellido;
        }

        /** También muestra el segundo apellido con el nombre anterior para aplicaciones que aún lo utilizan. */
        @JsonProperty(value = "apellidoMaterno", access = JsonProperty.Access.READ_ONLY)
        public String aliasSegundoApellido() {
            return segundoApellido;
        }
    }

    public record EstacionamientoPanel(
            UUID id,
            String nombre,
            TipoEstacionamiento tipo,
            HorarioPanel horario) {
    }

    public record HorarioPanel(
            ModoHorario modo,
            String zonaHoraria,
            String horaApertura,
            String horaCierre) {
    }
}
