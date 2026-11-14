package mx.smartparking.ownerconsole.modelo;

import java.util.Arrays;
import java.util.Objects;

/** Mantiene en memoria el único borrador del asistente, incluidos sus secretos. */
public final class BorradorConfiguracion {

    private String nombres = "";
    private String primerApellido = "";
    private String segundoApellido = "";
    private String correo = "";
    private char[] contrasenaAcceso = new char[0];
    private char[] confirmacionAcceso = new char[0];
    private char[] contrasenaAdministrativa = new char[0];
    private char[] confirmacionAdministrativa = new char[0];
    private String nombreEstacionamiento = "";
    private String tipoEstacionamiento = "";
    private String modoHorario = "";
    private String zonaHoraria = "";
    private String horaApertura = "";
    private String horaCierre = "";
    private long revision;

    public void actualizarIdentidad(String nuevosNombres, String nuevoPrimerApellido, String nuevoSegundoApellido) {
        if (!Objects.equals(nombres, nuevosNombres)
                || !Objects.equals(primerApellido, nuevoPrimerApellido)
                || !Objects.equals(segundoApellido, nuevoSegundoApellido)) {
            revision++;
        }
        nombres = nuevosNombres;
        primerApellido = nuevoPrimerApellido;
        segundoApellido = nuevoSegundoApellido;
    }

    /**
     * guarda el correo y copia los caracteres de la contraseña y su confirmación
     * borra los caracteres anteriores y recibidos y registra si cambiaron los datos
     */
    public void actualizarAcceso(String nuevoCorreo, char[] nuevaContrasena, char[] nuevaConfirmacion) {
        boolean cambio = !Objects.equals(correo, nuevoCorreo)
                || !Arrays.equals(contrasenaAcceso, nuevaContrasena)
                || !Arrays.equals(confirmacionAcceso, nuevaConfirmacion);
        contrasenaAcceso = reemplazarSecreto(contrasenaAcceso, nuevaContrasena);
        confirmacionAcceso = reemplazarSecreto(confirmacionAcceso, nuevaConfirmacion);
        correo = nuevoCorreo;
        if (cambio) {
            revision++;
        }
    }

    /**
     * guarda el correo y la contraseña sin mantener una confirmación de acceso
     * usa el otro método para limpiar los caracteres y registrar los cambios
     */
    public void actualizarAcceso(String nuevoCorreo, char[] nuevaContrasena) {
        actualizarAcceso(nuevoCorreo, nuevaContrasena, new char[0]);
    }

    /**
     * guarda una copia de la contraseña de administración y su confirmación
     * borra los caracteres anteriores y recibidos y registra si hubo cambios
     */
    public void actualizarAdministracion(char[] nuevaContrasena, char[] nuevaConfirmacion) {
        boolean cambio = !Arrays.equals(contrasenaAdministrativa, nuevaContrasena)
                || !Arrays.equals(confirmacionAdministrativa, nuevaConfirmacion);
        contrasenaAdministrativa = reemplazarSecreto(contrasenaAdministrativa, nuevaContrasena);
        confirmacionAdministrativa = reemplazarSecreto(confirmacionAdministrativa, nuevaConfirmacion);
        if (cambio) {
            revision++;
        }
    }

    public void actualizarEstacionamiento(String nuevoNombre, String nuevoTipo) {
        if (!Objects.equals(nombreEstacionamiento, nuevoNombre)
                || !Objects.equals(tipoEstacionamiento, nuevoTipo)) {
            revision++;
        }
        nombreEstacionamiento = nuevoNombre;
        tipoEstacionamiento = nuevoTipo;
    }

    public void actualizarHorario(
            String nuevoModo,
            String nuevaZonaHoraria,
            String nuevaHoraApertura,
            String nuevaHoraCierre) {
        if (!Objects.equals(modoHorario, nuevoModo)
                || !Objects.equals(zonaHoraria, nuevaZonaHoraria)
                || !Objects.equals(horaApertura, nuevaHoraApertura)
                || !Objects.equals(horaCierre, nuevaHoraCierre)) {
            revision++;
        }
        modoHorario = nuevoModo;
        zonaHoraria = nuevaZonaHoraria;
        horaApertura = nuevaHoraApertura;
        horaCierre = nuevaHoraCierre;
    }

    public String nombres() {
        return nombres;
    }

    public String primerApellido() {
        return primerApellido;
    }

    public String segundoApellido() {
        return segundoApellido;
    }

    public String correo() {
        return correo;
    }

    public char[] copiarContrasenaAcceso() {
        return contrasenaAcceso.clone();
    }

    public char[] copiarConfirmacionAcceso() {
        return confirmacionAcceso.clone();
    }

    public char[] copiarContrasenaAdministrativa() {
        return contrasenaAdministrativa.clone();
    }

    public char[] copiarConfirmacionAdministrativa() {
        return confirmacionAdministrativa.clone();
    }

    public String nombreEstacionamiento() {
        return nombreEstacionamiento;
    }

    public String tipoEstacionamiento() {
        return tipoEstacionamiento;
    }

    public String modoHorario() {
        return modoHorario;
    }

    public String zonaHoraria() {
        return zonaHoraria;
    }

    public String horaApertura() {
        return horaApertura;
    }

    public String horaCierre() {
        return horaCierre;
    }

    /** Cambia al editar el borrador y permite conservar una clave idempotente si no cambió. */
    public long revision() {
        return revision;
    }

    /** Borra los cuatro campos secretos y deja el resto del borrador intacto. */
    public void limpiarSecretos() {
        borrar(contrasenaAcceso);
        borrar(confirmacionAcceso);
        borrar(contrasenaAdministrativa);
        borrar(confirmacionAdministrativa);
        contrasenaAcceso = new char[0];
        confirmacionAcceso = new char[0];
        contrasenaAdministrativa = new char[0];
        confirmacionAdministrativa = new char[0];
        revision++;
    }

    private static char[] reemplazarSecreto(char[] anterior, char[] nuevo) {
        borrar(anterior);
        char[] copia = nuevo.clone();
        borrar(nuevo);
        return copia;
    }

    private static void borrar(char[] secreto) {
        Arrays.fill(secreto, '\0');
    }
}
