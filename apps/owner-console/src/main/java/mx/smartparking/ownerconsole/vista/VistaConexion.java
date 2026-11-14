package mx.smartparking.ownerconsole.vista;

import java.util.function.Consumer;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.VBox;

/** Pantalla de espera y recuperación cuando la API no responde. */
public final class VistaConexion extends BorderPane {

    private final Label detalle = new Label();
    private final Button reintentar = new Button("Intentar de nuevo");

    public VistaConexion(Consumer<Void> alReintentar) {
        BorderPane marco = VistaComun.crearMarco("Conexión");
        Label titulo = new Label("No se pudo cargar la información");
        titulo.getStyleClass().add("title-2");
        detalle.setWrapText(true);
        detalle.getStyleClass().add("text-muted");
        reintentar.getStyleClass().add("accent");
        reintentar.setOnAction(evento -> alReintentar.accept(null));
        VBox tarjeta = VistaComun.crearTarjeta();
        tarjeta.getChildren().addAll(titulo, detalle, reintentar);
        tarjeta.setAlignment(Pos.CENTER_LEFT);
        marco.setCenter(tarjeta);
        setCenter(marco.getCenter());
        setTop(marco.getTop());
        setPadding(marco.getPadding());
        getStyleClass().add("fondo-aplicacion");
    }

    public void mostrarMensaje(String texto, boolean ocupado) {
        detalle.setText(texto);
        reintentar.setDisable(ocupado);
        reintentar.setText(ocupado ? "Cargando…" : "Intentar de nuevo");
    }
}
