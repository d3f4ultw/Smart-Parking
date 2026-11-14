package mx.smartparking.api.configuracion;

import com.fasterxml.jackson.annotation.JsonAlias;
import java.time.LocalTime;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * Reúne los datos necesarios para configurar el estacionamiento por primera vez o terminar un cambio
 * de propietario.
 */
public record SolicitudConfiguracion(
        PropietarioSolicitud propietario,
        EstacionamientoSolicitud estacionamiento) {

    private static final Pattern CORREO = Pattern.compile("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$");

    public DatosConfiguracion validar() {
        if (propietario == null || estacionamiento == null || estacionamiento.horario() == null) {
            throw new IllegalArgumentException("Completa los datos del propietario, estacionamiento y horario.");
        }
        String nombres = texto(propietario.nombres(), "tu nombre", 120);
        String primerApellido = texto(propietario.primerApellido(), "tu primer apellido", 80);
        String segundoApellido = textoOpcional(propietario.segundoApellido(), "el segundo apellido");
        String correo = propietario.correo() == null ? "" : propietario.correo().trim().toLowerCase(Locale.ROOT);
        if (correo.length() > 254 || !CORREO.matcher(correo).matches()) {
            throw new IllegalArgumentException("Escribe un correo válido.");
        }
        validarContrasena(propietario.contrasenaAcceso(), "contraseña de acceso");
        validarContrasena(propietario.contrasenaAdministrativa(), "contraseña administrativa");
        if (propietario.contrasenaAcceso().equals(propietario.contrasenaAdministrativa())) {
            throw new IllegalArgumentException("Las contraseñas de acceso y administración deben ser distintas.");
        }

        String nombreEstacionamiento = texto(estacionamiento.nombre(), "nombre del estacionamiento", 120);
        if (estacionamiento.tipo() == null) {
            throw new IllegalArgumentException("Selecciona el tipo de estacionamiento.");
        }
        HorarioSolicitud horarioSolicitud = estacionamiento.horario();
        LocalTime apertura = null;
        LocalTime cierre = null;
        if (horarioSolicitud.modo() == ModoHorario.INTERVALO_DIARIO) {
            apertura = HorarioConfiguracion.parsearHora(horarioSolicitud.horaApertura(), "apertura");
            cierre = HorarioConfiguracion.parsearHora(horarioSolicitud.horaCierre(), "cierre");
        } else if (horarioSolicitud.horaApertura() != null || horarioSolicitud.horaCierre() != null) {
            throw new IllegalArgumentException("Para abrir todo el día, deja vacías las horas de apertura y cierre.");
        }
        HorarioConfiguracion horario = new HorarioConfiguracion(
                horarioSolicitud.modo(),
                horarioSolicitud.zonaHoraria(),
                apertura,
                cierre);
        return new DatosConfiguracion(
                new DatosPropietario(
                        nombres,
                        primerApellido,
                        segundoApellido,
                        correo,
                        propietario.contrasenaAcceso(),
                        propietario.contrasenaAdministrativa()),
                nombreEstacionamiento,
                estacionamiento.tipo(),
                horario);
    }

    private static String texto(String valor, String campo, int maximo) {
        if (valor == null || valor.isBlank()) {
            throw new IllegalArgumentException("Escribe " + campo + ".");
        }
        if (valor.strip().length() > maximo) {
            throw new IllegalArgumentException("Escribe un texto más corto para " + campo + ".");
        }
        return valor.strip();
    }

    private static void validarContrasena(String valor, String campo) {
        if (valor == null || valor.codePointCount(0, valor.length()) < 10) {
            throw new IllegalArgumentException("Elige una contraseña más larga.");
        }
    }

    private static String textoOpcional(String valor, String campo) {
        if (valor == null || valor.isBlank()) {
            return null;
        }
        if (valor.strip().length() > 80) {
            throw new IllegalArgumentException("Escribe un texto más corto para " + campo + ".");
        }
        return valor.strip();
    }

    @Override
    public String toString() {
        return "SolicitudConfiguracion[propietario=[REDACTADO], estacionamiento="
                + (estacionamiento == null ? "null" : estacionamiento.nombre()) + "]";
    }

    public record PropietarioSolicitud(
            String nombres,
            @JsonAlias("apellidoPaterno")
            String primerApellido,
            @JsonAlias("apellidoMaterno")
            String segundoApellido,
            String correo,
            String contrasenaAcceso,
            String contrasenaAdministrativa) {
        @Override
        public String toString() {
            return "PropietarioSolicitud[datos=[REDACTADOS]]";
        }
    }

    public record EstacionamientoSolicitud(
            String nombre,
            TipoEstacionamiento tipo,
            HorarioSolicitud horario) {
    }

    public record HorarioSolicitud(
            ModoHorario modo,
            String zonaHoraria,
            String horaApertura,
            String horaCierre) {
    }
}
