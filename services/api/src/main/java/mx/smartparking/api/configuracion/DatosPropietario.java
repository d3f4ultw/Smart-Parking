package mx.smartparking.api.configuracion;

/** Reúne el nombre, correo y contraseñas necesarios para configurar al propietario. */
public record DatosPropietario(
        String nombres,
        String primerApellido,
        String segundoApellido,
        String correo,
        String contrasenaAcceso,
        String contrasenaAdministrativa) {

    @Override
    public String toString() {
        return "DatosPropietario[datos=[REDACTADOS]]";
    }
}
