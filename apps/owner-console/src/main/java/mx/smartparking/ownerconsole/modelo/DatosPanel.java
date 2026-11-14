package mx.smartparking.ownerconsole.modelo;

/** reúne la información que aparece en el panel del propietario y no incluye contraseñas. */
public record DatosPanel(
        long revision,
        long revisionPropietario,
        Propietario propietario,
        Estacionamiento estacionamiento,
        String etag) {

    public record Propietario(
            String nombres,
            String primerApellido,
            String segundoApellido,
            String correo) {
        public String nombreCompleto() {
        return java.util.stream.Stream.of(nombres, primerApellido, segundoApellido)
                .filter(valor -> valor != null && !valor.isBlank())
                .collect(java.util.stream.Collectors.joining(" "));
        }
    }

    public record Estacionamiento(
            String id,
            String nombre,
            String tipo,
            Horario horario) {
    }

    public record Horario(
            String modo,
            String zonaHoraria,
            String horaApertura,
            String horaCierre) {
        public String descripcion() {
            if ("CONTINUO_24_7".equals(modo)) {
                return "Abierto todo el día · " + zonaHoraria;
            }
            return horaApertura + "–" + horaCierre + " · " + zonaHoraria;
        }
    }
}
