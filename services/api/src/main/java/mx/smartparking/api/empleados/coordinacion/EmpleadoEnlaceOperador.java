package mx.smartparking.api.empleados.coordinacion;

/** Reúne los datos del empleado que se necesitan para revisar un cambio en su cuenta de operador. */
public record EmpleadoEnlaceOperador(
        long id, String codigo, String estado, long revision, String correo, String correoNormalizado) {
}
