package mx.smartparking.ownerconsole.vista.configuracion;

import java.util.Arrays;

/** conserva por un momento los datos que el usuario escribe en el asistente. */
public final class FormularioAsistente {

    private String nombres = "";
    private String primerApellido = "";
    private String segundoApellido = "";
    private String correo = "";
    private char[] contrasenaAcceso = new char[0];
    private char[] contrasenaAdministrativa = new char[0];
    private char[] confirmacionAdministrativa = new char[0];
    private String nombreEstacionamiento = "";
    private String tipoEstacionamiento = "";
    private String modoHorario = "";
    private String zonaHoraria = "";
    private String horaApertura = "09:00";
    private String horaCierre = "18:00";

    public void actualizarIdentidad(String nuevosNombres, String nuevoPrimerApellido, String nuevoSegundoApellido) {
        nombres = valor(nuevosNombres);
        primerApellido = valor(nuevoPrimerApellido);
        segundoApellido = valor(nuevoSegundoApellido);
    }

    public void actualizarAcceso(String nuevoCorreo, char[] nuevaContrasena) {
        correo = valor(nuevoCorreo);
        contrasenaAcceso = reemplazar(contrasenaAcceso, nuevaContrasena);
    }

    public void actualizarAdministracion(char[] nuevaContrasena, char[] nuevaConfirmacion) {
        contrasenaAdministrativa = reemplazar(contrasenaAdministrativa, nuevaContrasena);
        confirmacionAdministrativa = reemplazar(confirmacionAdministrativa, nuevaConfirmacion);
    }

    public void actualizarEstacionamiento(String nuevoNombre, String nuevoTipo) {
        nombreEstacionamiento = valor(nuevoNombre);
        tipoEstacionamiento = valor(nuevoTipo);
    }

    public void actualizarHorario(String nuevoModo, String nuevaZona, String nuevaApertura, String nuevoCierre) {
        modoHorario = valor(nuevoModo);
        zonaHoraria = valor(nuevaZona);
        horaApertura = valor(nuevaApertura);
        horaCierre = valor(nuevoCierre);
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

    public void limpiarSecretos() {
        borrar(contrasenaAcceso);
        borrar(contrasenaAdministrativa);
        borrar(confirmacionAdministrativa);
        contrasenaAcceso = new char[0];
        contrasenaAdministrativa = new char[0];
        confirmacionAdministrativa = new char[0];
    }

    private static char[] reemplazar(char[] anterior, char[] nuevo) {
        borrar(anterior);
        char[] copia = nuevo == null ? new char[0] : nuevo.clone();
        borrar(nuevo);
        return copia;
    }

    private static void borrar(char[] secreto) {
        if (secreto != null) {
            Arrays.fill(secreto, '\0');
        }
    }

    private static String valor(String valor) {
        return valor == null ? "" : valor;
    }
}
