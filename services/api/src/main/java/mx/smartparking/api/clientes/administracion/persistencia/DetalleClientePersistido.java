package mx.smartparking.api.clientes.administracion.persistencia;

import java.time.Instant;

/** Reúne los datos guardados del cliente y su membresía para mostrarlos al personal autorizado. */
public record DetalleClientePersistido(
        String codigo,
        String nombres,
        String primerApellido,
        String segundoApellido,
        String estadoMembresia,
        Instant periodoInicio,
        Instant periodoFin,
        Instant siguienteCobroEn,
        boolean cancelacionAlFinal) {
}
