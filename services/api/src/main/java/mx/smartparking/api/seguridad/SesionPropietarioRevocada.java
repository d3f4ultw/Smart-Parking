package mx.smartparking.api.seguridad;

/** Comunica que una sesión se cerró usando una referencia que no revela su identificador. */
public record SesionPropietarioRevocada(String huellaSesion) {
}
