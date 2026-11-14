package mx.smartparking.ownerconsole.controlador.sesion;

import java.util.function.Consumer;
import java.util.regex.Pattern;
import javafx.application.Platform;
import javafx.scene.Node;
import mx.smartparking.ownerconsole.controlador.EjecutorJavaFx;
import mx.smartparking.ownerconsole.modelo.SesionPropietario;
import mx.smartparking.ownerconsole.servicio.ClienteSesionPropietario;
import mx.smartparking.ownerconsole.servicio.FalloApi;
import mx.smartparking.ownerconsole.vista.VistaAcceso;
import mx.smartparking.ownerconsole.vista.VistaPanel;

/** Coordina el acceso, la consulta y el cierre de la sesión del propietario. */
public final class ControladorSesionPropietario {

    private static final Pattern FORMATO_CORREO = Pattern.compile("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$");
    private final ClienteSesionPropietario cliente;
    private final EjecutorJavaFx ejecutor;
    private final Consumer<Node> mostrarVista;
    private final Consumer<String> alAutenticado;
    private final Consumer<String> alMostrarConexion;
    private VistaAcceso vistaAcceso;

    public ControladorSesionPropietario(
            ClienteSesionPropietario cliente,
            EjecutorJavaFx ejecutor,
            Consumer<Node> mostrarVista,
            Consumer<String> alAutenticado,
            Consumer<String> alMostrarConexion) {
        this.cliente = cliente;
        this.ejecutor = ejecutor;
        this.mostrarVista = mostrarVista;
        this.alAutenticado = alAutenticado;
        this.alMostrarConexion = alMostrarConexion;
    }

    public void comprobarSesion() {
        ejecutor.ejecutar(cliente::consultarSesion, sesion -> {
            if (sesion.autenticada()) {
                alAutenticado.accept(null);
            } else {
                mostrarAcceso("");
            }
        }, error -> {
            if (incierto(error)) {
                alMostrarConexion.accept("No pudimos confirmar si ya entraste. Inténtalo de nuevo.");
            } else if (error instanceof FalloApi fallo && fallo.estadoHttp() == 401) {
                mostrarAcceso("Tu acceso venció. Inicia sesión de nuevo.");
            } else {
                alMostrarConexion.accept("No pudimos comprobar si ya entraste. Revisa tu conexión.");
            }
        });
    }

    public void mostrarAcceso(String mensaje) {
        vistaAcceso = new VistaAcceso(this::iniciarSesion);
        vistaAcceso.mostrarEstado(mensaje, false);
        mostrarVista.accept(vistaAcceso);
        Platform.runLater(vistaAcceso::enfocarCorreo);
    }

    public void cerrarSesion(VistaPanel vistaPanel) {
        vistaPanel.mostrarEstado("Cerrando sesión…", true);
        ejecutor.ejecutar(() -> {
            cliente.cerrarSesion();
            return Boolean.TRUE;
        }, ignorado -> mostrarAcceso(""), error -> {
            if (incierto(error)) {
                resolverCierreIncierto();
            } else {
                vistaPanel.mostrarEstado(mensaje(error), false);
            }
        });
    }

    private void iniciarSesion(String correo, String contrasena) {
        String valorCorreo = correo == null ? "" : correo.trim();
        String valorContrasena = contrasena == null ? "" : contrasena;
        String errorCorreo = valorCorreo.isBlank()
                ? "Este campo es obligatorio."
                : valorCorreo.length() > 254 || !FORMATO_CORREO.matcher(valorCorreo).matches()
                        ? "Ingresa un correo válido."
                        : "";
        String errorContrasena = valorContrasena.isEmpty() ? "Este campo es obligatorio." : "";
        if (!errorCorreo.isBlank() || !errorContrasena.isBlank()) {
            vistaAcceso.mostrarErrores(errorCorreo, errorContrasena);
            return;
        }
        vistaAcceso.mostrarErrores("", "");
        vistaAcceso.limpiarContrasena();
        vistaAcceso.mostrarEstado("Comprobando tus datos…", true);
        ejecutor.ejecutar(
                () -> cliente.iniciarSesion(correo, contrasena),
                sesion -> {
                    if (sesion.autenticada()) {
                        alAutenticado.accept(null);
                    } else {
                        vistaAcceso.mostrarErrorCredenciales();
                    }
                },
                error -> {
                    if (incierto(error)) {
                        resolverLoginIncierto();
                    } else if (error instanceof FalloApi fallo && fallo.estadoHttp() == 401) {
                        vistaAcceso.mostrarErrorCredenciales();
                    } else {
                        vistaAcceso.mostrarEstado(mensaje(error), false);
                    }
                });
    }

    private void resolverLoginIncierto() {
        vistaAcceso.mostrarEstado("Comprobando si pudimos iniciar tu acceso…", true);
        ejecutor.ejecutar(cliente::consultarSesion, sesion -> {
            if (sesion.autenticada()) {
                alAutenticado.accept("Ya entraste.");
            } else {
                vistaAcceso.mostrarEstado(
                        "No pudimos confirmar tu acceso. Escribe de nuevo tu contraseña para intentarlo otra vez.", false);
            }
        }, error -> mostrarAcceso("No pudimos confirmar si entraste. Revisa tu conexión e inténtalo más tarde."));
    }

    private void resolverCierreIncierto() {
        ejecutor.ejecutar(cliente::consultarSesion, sesion -> {
            if (sesion.autenticada()) {
                alAutenticado.accept("Sigues dentro. Intenta cerrar sesión otra vez.");
            } else {
                mostrarAcceso("");
            }
        }, this::manejarErrorPanel);
    }

    private void manejarErrorPanel(Throwable error) {
        if (error instanceof FalloApi fallo && fallo.estadoHttp() == 401) {
            mostrarAcceso("Tu acceso venció. Inicia sesión de nuevo.");
        } else {
            alMostrarConexion.accept(
                    "No pudimos cargar tu información. Revisa tu conexión para continuar.");
        }
    }

    private boolean incierto(Throwable error) {
        return error instanceof FalloApi fallo && fallo.respuestaIncierta();
    }

    private String mensaje(Throwable error) {
        return error instanceof FalloApi fallo
                ? fallo.getMessage()
                : "No pudimos completar la acción. Revisa tu conexión e inténtalo de nuevo.";
    }
}
