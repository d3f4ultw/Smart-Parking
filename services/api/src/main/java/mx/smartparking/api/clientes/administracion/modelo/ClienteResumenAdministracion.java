package mx.smartparking.api.clientes.administracion.modelo;

import mx.smartparking.api.clientes.modelo.EstadoMembresia;

/** Reúne el código, nombre y estado de membresía que se muestran en la lista de clientes. */
public record ClienteResumenAdministracion(
        String codigo,
        String nombreCompleto,
        EstadoMembresia estadoMembresia) {
}
