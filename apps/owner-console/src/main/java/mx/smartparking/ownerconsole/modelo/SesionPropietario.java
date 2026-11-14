package mx.smartparking.ownerconsole.modelo;

/** Estado no secreto de una sesión consultada en la API. */
public record SesionPropietario(boolean autenticada, String correo, long revisionPropietario) {
}
