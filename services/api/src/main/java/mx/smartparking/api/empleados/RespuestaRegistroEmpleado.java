package mx.smartparking.api.empleados;

/** Contiene el resultado de registrar un empleado; se conserva si se repite la misma solicitud. */
public record RespuestaRegistroEmpleado(long id, String codigo, String idTexto) {

    public RespuestaRegistroEmpleado {
        idTexto = Long.toString(id);
    }

    public RespuestaRegistroEmpleado(long id, String codigo) {
        this(id, codigo, Long.toString(id));
    }
}
