package mx.smartparking.api.empleados;

/** Reúne el nombre, los apellidos y el correo opcional para registrar a un empleado. */
public record SolicitudRegistroEmpleado(
        String nombres,
        String primerApellido,
        String segundoApellido,
        String correo) {

    /** Permite seguir creando solicitudes con los datos que se usaban anteriormente. */
    public SolicitudRegistroEmpleado(String nombres, String primerApellido, String segundoApellido) {
        this(nombres, primerApellido, segundoApellido, null);
    }
}
