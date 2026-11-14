package mx.smartparking.ownerconsole.vista;

import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.Node;
import javafx.scene.control.Label;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.Region;
import javafx.scene.layout.VBox;

/** Elementos visuales compartidos por las pantallas de la consola. */
public final class VistaComun {

    private VistaComun() {
    }

    public static BorderPane crearMarco(String titulo) {
        BorderPane marco = new BorderPane();
        marco.getStyleClass().add("fondo-aplicacion");
        marco.setPadding(new Insets(28, 36, 24, 36));
        Label marca = new Label("SMART PARKING");
        marca.getStyleClass().addAll("text-small", "text-muted", "marca");
        Label nombre = new Label(titulo);
        nombre.getStyleClass().add("title-3");
        boolean mostrarTitulo = titulo != null && !titulo.isBlank();
        VBox encabezado = mostrarTitulo ? new VBox(6, marca, nombre) : new VBox(6, marca);
        encabezado.setPadding(new Insets(0, 0, mostrarTitulo ? 24 : 6, 0));
        marco.setTop(encabezado);
        return marco;
    }

    public static VBox crearTarjeta() {
        VBox tarjeta = new VBox(18);
        tarjeta.getStyleClass().add("tarjeta");
        tarjeta.setMaxWidth(680);
        tarjeta.setPadding(new Insets(28));
        tarjeta.setAlignment(Pos.TOP_LEFT);
        return tarjeta;
    }

    public static VBox crearCampo(String etiqueta, Node control, String textoAyuda, Label error) {
        Label nombre = new Label(etiqueta);
        nombre.getStyleClass().add("label-campo");
        nombre.setLabelFor(control);
        if (control instanceof javafx.scene.control.Labeled labeled) {
            labeled.setAccessibleText(etiqueta);
        }
        VBox campo = new VBox(4, nombre, control);
        VBox.setVgrow(control, Priority.NEVER);
        control.setAccessibleHelp(textoAyuda == null ? "" : textoAyuda);
        if (textoAyuda != null && !textoAyuda.isBlank()) {
            Label ayuda = new Label(textoAyuda);
            ayuda.getStyleClass().add("texto-ayuda");
            ayuda.setWrapText(true);
            campo.getChildren().add(ayuda);
        }
        error.getStyleClass().add("error-campo");
        error.setWrapText(true);
        error.setVisible(false);
        error.setManaged(false);
        error.textProperty().addListener((observable, textoAnterior, textoNuevo) -> {
            boolean visible = textoNuevo != null && !textoNuevo.isBlank();
            error.setVisible(visible);
            error.setManaged(visible);
        });
        campo.getChildren().add(error);
        return campo;
    }

    public static Label crearMensajeEstado() {
        Label mensaje = new Label();
        mensaje.getStyleClass().add("mensaje-estado");
        mensaje.setWrapText(true);
        mensaje.setMinHeight(24);
        return mensaje;
    }

    public static HBox crearAcciones(Node... acciones) {
        HBox contenedor = new HBox(12, acciones);
        contenedor.setAlignment(Pos.CENTER_RIGHT);
        contenedor.getStyleClass().add("barra-acciones");
        return contenedor;
    }

    public static Region separadorFlexible() {
        Region espacio = new Region();
        HBox.setHgrow(espacio, Priority.ALWAYS);
        return espacio;
    }
}
