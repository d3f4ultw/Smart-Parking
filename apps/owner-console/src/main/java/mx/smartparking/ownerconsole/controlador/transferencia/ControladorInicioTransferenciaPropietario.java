package mx.smartparking.ownerconsole.controlador.transferencia;

import java.util.UUID;
import java.util.function.Consumer;
import javafx.scene.control.Alert;
import javafx.scene.control.ButtonType;
import javafx.stage.Stage;
import mx.smartparking.ownerconsole.controlador.EjecutorJavaFx;
import mx.smartparking.ownerconsole.modelo.DatosPanel;
import mx.smartparking.ownerconsole.modelo.EstadoConfiguracion;
import mx.smartparking.ownerconsole.servicio.ClienteConfiguracionPropietario;
import mx.smartparking.ownerconsole.servicio.ClienteTransferenciaPropietario;
import mx.smartparking.ownerconsole.servicio.FalloApi;
import mx.smartparking.ownerconsole.servicio.ResultadoTransicion;
import mx.smartparking.ownerconsole.vista.VistaPanel;

/** Gestiona la autorización inicial que desvincula al propietario vigente. */
final class ControladorInicioTransferenciaPropietario {

    private final Stage escenario;
    private final ClienteTransferenciaPropietario cliente;
    private final ClienteConfiguracionPropietario clienteConfiguracion;
    private final EjecutorJavaFx ejecutor;
    private final Consumer<String> alMostrarConexion;
    private final Consumer<String> alCargarPanel;
    private final Consumer<ResultadoTransicion> alInicioConfirmado;
    private final Consumer<String> alRecuperar;
    private String claveInicio;
    private String etagInicio;

    ControladorInicioTransferenciaPropietario(
            Stage escenario,
            ClienteTransferenciaPropietario cliente,
            ClienteConfiguracionPropietario clienteConfiguracion,
            EjecutorJavaFx ejecutor,
            Consumer<String> alMostrarConexion,
            Consumer<String> alCargarPanel,
            Consumer<ResultadoTransicion> alInicioConfirmado,
            Consumer<String> alRecuperar) {
        this.escenario = escenario;
        this.cliente = cliente;
        this.clienteConfiguracion = clienteConfiguracion;
        this.ejecutor = ejecutor;
        this.alMostrarConexion = alMostrarConexion;
        this.alCargarPanel = alCargarPanel;
        this.alInicioConfirmado = alInicioConfirmado;
        this.alRecuperar = alRecuperar;
    }

    void preparar(DatosPanel panel, VistaPanel vistaPanel) {
        Alert confirmacion = new Alert(Alert.AlertType.CONFIRMATION);
        confirmacion.initOwner(escenario);
        confirmacion.setTitle("Cambiar propietario");
        confirmacion.setHeaderText("El propietario actual perderá el acceso de inmediato");
        confirmacion.setContentText(
                "Al continuar, la persona que administra ahora perderá el acceso. Tendrás que completar de nuevo "
                        + "la configuración del estacionamiento. Si cierras la aplicación antes de terminar, "
                        + "necesitarás la contraseña anterior de administración para seguir.");
        ButtonType continuar = new ButtonType("Cambiar propietario");
        confirmacion.getButtonTypes().setAll(continuar, ButtonType.CANCEL);
        if (confirmacion.showAndWait().orElse(ButtonType.CANCEL) != continuar) {
            vistaPanel.limpiarContrasenaAdministrativa();
            return;
        }

        String contrasena = vistaPanel.leerContrasenaAdministrativa();
        vistaPanel.limpiarContrasenaAdministrativa();
        if (contrasena == null || contrasena.isEmpty()) {
            vistaPanel.mostrarErrorAdministrativo("Escribe la contraseña de administración.");
            return;
        }
        vistaPanel.mostrarErrorAdministrativo("");
        if (claveInicio == null || !panel.etag().equals(etagInicio)) {
            claveInicio = UUID.randomUUID().toString();
            etagInicio = panel.etag();
        }
        String clave = claveInicio;
        vistaPanel.mostrarEstado("Comprobando la contraseña y preparando el cambio…", true);
        ejecutor.ejecutar(
                () -> cliente.iniciarTransferencia(contrasena, panel, clave),
                alInicioConfirmado,
                error -> manejarFallo(error, vistaPanel));
    }

    void limpiar() {
        claveInicio = null;
        etagInicio = null;
    }

    static String textoAvisoTransferencia(String estadoCorreo) {
        return switch (estadoCorreo == null ? "" : estadoCorreo) {
            case "ENVIADO" -> "Avisamos por correo al propietario anterior.";
            case "FALLIDO" -> "No pudimos enviar el aviso. El cambio sigue pendiente.";
            case "DESHABILITADO" -> "No se pudo enviar el aviso. El cambio sigue pendiente.";
            case "DESCONOCIDO" -> "No sabemos si se envió el aviso.";
            default -> "El cambio de propietario sigue pendiente.";
        };
    }

    private void manejarFallo(Throwable error, VistaPanel vistaPanel) {
        if (incierto(error) || error instanceof FalloApi fallo && (fallo.estadoHttp() == 409 || fallo.estadoHttp() == 412)) {
            resolverIncierto();
        } else if (error instanceof FalloApi fallo && fallo.estadoHttp() == 403) {
            claveInicio = null;
            etagInicio = null;
            vistaPanel.mostrarEstado(
                    "La contraseña de administración no es correcta. El cambio no empezó.",
                    false);
        } else {
            if (error instanceof FalloApi fallo && fallo.estadoHttp() < 500) {
                claveInicio = null;
                etagInicio = null;
            }
            vistaPanel.mostrarEstado(mensaje(error), false);
        }
    }

    private void resolverIncierto() {
        alMostrarConexion.accept("Comprobando qué pasó antes de continuar…");
        ejecutor.ejecutar(clienteConfiguracion::consultarEstado, estado -> {
            if (estado == EstadoConfiguracion.TRANSFERENCIA_PENDIENTE) {
                claveInicio = null;
                etagInicio = null;
                alRecuperar.accept(
                        "El cambio ya empezó. Escribe de nuevo la contraseña de administración para continuar.");
            } else if (estado == EstadoConfiguracion.CONFIGURADA) {
                alCargarPanel.accept(
                        "El propietario actual conserva el acceso. Puedes volver a intentarlo cuando quieras.");
            } else {
                alMostrarConexion.accept("No pudimos comprobar cómo quedó el cambio. Revisa tu conexión antes de continuar.");
            }
        }, error -> alMostrarConexion.accept(
                "No pudimos comprobar qué pasó. Revisa tu conexión antes de volver a intentarlo."));
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
