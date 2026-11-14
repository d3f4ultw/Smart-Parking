package mx.smartparking.api.clientes.modelo;

import java.util.UUID;

/** Reúne el nombre y correo que el cliente puede ver en su cuenta, sin mostrar su contraseña. */
public record ClientePortal(
        UUID clienteId,
        String nombres,
        String primerApellido,
        String segundoApellido,
        String correo) {
}
