package mx.smartparking.ownerconsole;

import atlantafx.base.theme.PrimerLight;
import javafx.application.Application;
import javafx.scene.Scene;
import javafx.scene.control.Label;
import javafx.scene.layout.StackPane;
import javafx.stage.Stage;
import mx.smartparking.ownerconsole.controlador.ControladorAplicacion;
import mx.smartparking.ownerconsole.servicio.ClienteApi;

/** abre la consola del propietario y muestra la pantalla de configuración o acceso que corresponda. */
public final class AplicacionPropietario extends Application {

    private static final double ANCHO_MINIMO = 760;
    private static final double ALTO_MINIMO = 520;
    private static final double ANCHO_VENTANA = dimensionConfigurada(
            "smartparking.owner-console.window.width", 900, ANCHO_MINIMO);
    private static final double ALTO_VENTANA = dimensionConfigurada(
            "smartparking.owner-console.window.height", 620, ALTO_MINIMO);
    private ControladorAplicacion controlador;

    @Override
    public void start(Stage escenario) {
        Application.setUserAgentStylesheet(new PrimerLight().getUserAgentStylesheet());
        StackPane raiz = new StackPane();
        Scene escena = new Scene(raiz, ANCHO_VENTANA, ALTO_VENTANA);
        var estilos = getClass().getResource("estilos.css");
        if (estilos != null) {
            escena.getStylesheets().add(estilos.toExternalForm());
        }
        escenario.setTitle("Smart Parking · Propietario");
        escenario.setResizable(false);
        escenario.setMinWidth(ANCHO_MINIMO);
        escenario.setMinHeight(ALTO_MINIMO);
        escenario.setScene(escena);
        escenario.setWidth(ANCHO_VENTANA);
        escenario.setHeight(ALTO_VENTANA);
        escenario.setMaximized(false);
        escenario.setFullScreen(false);
        try {
            controlador = new ControladorAplicacion(escenario, raiz, new ClienteApi());
            escenario.setOnCloseRequest(evento -> controlador.cerrar());
            escenario.show();
            escenario.centerOnScreen();
            controlador.iniciar();
        } catch (IllegalArgumentException error) {
            Label mensaje = new Label("La dirección de conexión no es válida.");
            mensaje.setWrapText(true);
            raiz.getChildren().setAll(mensaje);
            escenario.show();
        }
    }

    public static void main(String[] argumentos) {
        launch(argumentos);
    }

    private static double dimensionConfigurada(String propiedad, double predeterminada, double minima) {
        try {
            double solicitada = Double.parseDouble(System.getProperty(propiedad, Double.toString(predeterminada)));
            return Double.isFinite(solicitada) && solicitada > 0
                    ? Math.max(solicitada, minima)
                    : predeterminada;
        } catch (NumberFormatException excepcion) {
            return predeterminada;
        }
    }
}
