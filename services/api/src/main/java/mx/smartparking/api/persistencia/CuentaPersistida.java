package mx.smartparking.api.persistencia;

import java.util.UUID;
import mx.smartparking.api.seguridad.RolCuenta;

/** Reúne los datos guardados que se necesitan para permitir el acceso a una cuenta. */
public record CuentaPersistida(
        UUID id,
        String nombres,
        String primerApellido,
        String segundoApellido,
        String correo,
        String correoNormalizado,
        RolCuenta rol,
        boolean activa,
        String hashContrasenaAcceso,
        long revisionAcceso) {

    public String nombreCompleto() {
        String sufijoSegundoApellido = segundoApellido == null ? "" : " " + segundoApellido;
        return (nombres + " " + primerApellido + sufijoSegundoApellido).strip();
    }
}
