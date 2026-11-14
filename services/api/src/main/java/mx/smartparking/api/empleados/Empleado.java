package mx.smartparking.api.empleados;

import java.util.Locale;
import java.util.UUID;

/** Reúne el nombre, código y estado de un empleado para mostrarlos en el directorio. */
public record Empleado(
        long id,
        String codigo,
        String nombres,
        String primerApellido,
        String segundoApellido,
        EstadoEmpleado estado,
        long revision,
        String idTexto,
        String revisionTexto,
        String correo,
        OperadorVinculado operador) {

    public Empleado {
        idTexto = Long.toString(id);
        revisionTexto = Long.toString(revision);
    }

    /** Permite seguir creando datos de empleado con los campos que usaban otras partes de la aplicación. */
    public Empleado(
            long id,
            String codigo,
            String nombres,
            String primerApellido,
            String segundoApellido,
            EstadoEmpleado estado,
            long revision) {
        this(id, codigo, nombres, primerApellido, segundoApellido, estado, revision,
                Long.toString(id), Long.toString(revision), null, null);
    }

    /** Crea el código que se muestra para identificar al empleado a partir de su número. */
    public static String codigoDe(long id) {
        return String.format(Locale.ROOT, "E-%04d", id);
    }

    /**
     * Indica si el empleado tiene una cuenta de operador y cuál es su estado, sin mostrar sus datos de
     * acceso.
     */
    public record OperadorVinculado(UUID id, String estado) {
    }
}
