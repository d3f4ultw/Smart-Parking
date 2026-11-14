package mx.smartparking.api.clientes.administracion.modelo;

import com.fasterxml.jackson.annotation.JsonInclude;
import mx.smartparking.api.clientes.modelo.EstadoMembresia;

/** Reúne los datos del cliente y, si tiene membresía, los datos que se muestran al consultarla. */
@JsonInclude(JsonInclude.Include.ALWAYS)
public record DetalleClienteAdministracion(
        String codigo,
        String nombreCompleto,
        EstadoMembresia estadoMembresia,
        DetalleMembresiaAdministracion membresia) {
}
