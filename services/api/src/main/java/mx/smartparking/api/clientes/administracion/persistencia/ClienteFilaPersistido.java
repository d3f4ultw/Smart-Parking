package mx.smartparking.api.clientes.administracion.persistencia;

/** Guarda los datos de un cliente para mostrarlo en la lista administrativa. */
public record ClienteFilaPersistido(
        String codigo,
        String nombres,
        String primerApellido,
        String segundoApellido,
        String estadoMembresia) {
}
