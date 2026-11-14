package mx.smartparking.api.operadores;

/** Reúne los datos revisados que se necesitan para crear una cuenta de operador pendiente de activación. */
public record DatosRegistroOperador(
        String nombres,
        String primerApellido,
        String segundoApellido,
        String correo) {

    @Override
    public String toString() {
        return "DatosRegistroOperador[datos=[REDACTADOS]]";
    }
}
