package mx.smartparking.api.operadores;

/** Reúne el nombre, los apellidos y el correo para invitar a una persona como operador. */
public record SolicitudRegistroOperador(
        String nombres,
        String primerApellido,
        String segundoApellido,
        String correo) {

    @Override
    public String toString() {
        return "SolicitudRegistroOperador[datos=[REDACTADOS]]";
    }
}
