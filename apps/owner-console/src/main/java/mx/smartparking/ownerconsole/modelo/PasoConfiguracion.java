package mx.smartparking.ownerconsole.modelo;

/** indica en qué orden aparecen los seis pasos y qué título se muestra en cada uno. */
public enum PasoConfiguracion {
    IDENTIDAD("Propietario", "Datos del propietario"),
    ACCESO("Acceso", "Correo y contraseña de acceso"),
    ADMINISTRACION("Seguridad", "Contraseña de administración"),
    ESTACIONAMIENTO("Estacionamiento", "Datos del estacionamiento"),
    HORARIO("Horario", "Horario y zona horaria"),
    REVISION("Revisión", "Revisa la configuración");

    private final String etiqueta;
    private final String titulo;

    PasoConfiguracion(String etiqueta, String titulo) {
        this.etiqueta = etiqueta;
        this.titulo = titulo;
    }

    public String etiqueta() {
        return etiqueta;
    }

    public String titulo() {
        return titulo;
    }
}
