package mx.smartparking.api.configuracion;

import java.time.LocalTime;
import java.util.Locale;

/** Reúne el tipo y el horario que el propietario desea cambiar desde su panel. */
public record ActualizarDatosEstacionamientoSolicitud(String tipo, HorarioSolicitud horario) {

    public DatosEditables validar() {
        TipoEstacionamiento tipoValidado;
        try {
            tipoValidado = TipoEstacionamiento.valueOf(tipo == null ? "" : tipo.strip().toUpperCase(Locale.ROOT));
        } catch (IllegalArgumentException excepcion) {
            throw new IllegalArgumentException("Selecciona un tipo de estacionamiento.");
        }
        if (horario == null) {
            throw new IllegalArgumentException("Completa el horario del estacionamiento.");
        }

        ModoHorario modo;
        try {
            modo = ModoHorario.valueOf(horario.modo() == null ? "" : horario.modo().strip().toUpperCase(Locale.ROOT));
        } catch (IllegalArgumentException excepcion) {
            throw new IllegalArgumentException("Selecciona un horario de atención.");
        }

        LocalTime apertura = null;
        LocalTime cierre = null;
        if (modo == ModoHorario.CONTINUO_24_7) {
            if (noVacio(horario.horaApertura()) || noVacio(horario.horaCierre())) {
                throw new IllegalArgumentException("Para abrir todo el día, deja vacías las horas de apertura y cierre.");
            }
        } else {
            apertura = HorarioConfiguracion.parsearHora(horario.horaApertura(), "apertura");
            cierre = HorarioConfiguracion.parsearHora(horario.horaCierre(), "cierre");
        }

        return new DatosEditables(
                tipoValidado,
                new HorarioConfiguracion(modo, horario.zonaHoraria(), apertura, cierre));
    }

    private static boolean noVacio(String valor) {
        return valor != null && !valor.isBlank();
    }

    public record HorarioSolicitud(
            String modo,
            String zonaHoraria,
            String horaApertura,
            String horaCierre) {
    }

    public record DatosEditables(TipoEstacionamiento tipo, HorarioConfiguracion horario) {
    }
}
