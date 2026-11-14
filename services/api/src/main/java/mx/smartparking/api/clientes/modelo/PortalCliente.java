package mx.smartparking.api.clientes.modelo;

/** Reúne los datos personales y la membresía que el cliente puede consultar en su cuenta. */
public record PortalCliente(ClientePortal cliente, MembresiaPortal membresia) {
}
