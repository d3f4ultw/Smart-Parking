package mx.smartparking.ownerconsole.vista;

import java.util.function.Consumer;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.PasswordField;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.VBox;

/** Solicita la contraseña administrativa para reemitir una autorización limitada. */
public final class VistaRecuperacionTransferencia extends BorderPane {

    private final PasswordField contrasena = new PasswordField();
    private final Label mensaje = VistaComun.crearMensajeEstado();
    private final Button recuperar = new Button("Continuar cambio");

    public VistaRecuperacionTransferencia(Consumer<String> alRecuperar) {
        BorderPane marco = VistaComun.crearMarco("Cambio de propietario pendiente");
        Label descripcion = new Label(
                "El propietario anterior ya no puede entrar. Escribe su contraseña de administración "
                        + "para continuar. Esto no le devolverá el acceso.");
        descripcion.setWrapText(true);
        descripcion.getStyleClass().add("text-muted");
        contrasena.setPrefHeight(42);
        contrasena.setMaxWidth(Double.MAX_VALUE);
        recuperar.getStyleClass().add("accent");
        recuperar.setDefaultButton(true);
        recuperar.setOnAction(evento -> alRecuperar.accept(contrasena.getText()));
        VBox tarjeta = VistaComun.crearTarjeta();
        tarjeta.getChildren().addAll(
                descripcion,
                VistaComun.crearCampo("Contraseña de administración anterior", contrasena, null, new Label()),
                mensaje,
                recuperar);
        tarjeta.setAlignment(Pos.CENTER_LEFT);
        marco.setCenter(tarjeta);
        setTop(marco.getTop());
        setCenter(marco.getCenter());
        setPadding(marco.getPadding());
        getStyleClass().add("fondo-aplicacion");
    }

    public void mostrarEstado(String texto, boolean ocupado) {
        mensaje.setText(texto == null ? "" : texto);
        setDisable(ocupado);
        recuperar.setDisable(ocupado);
        recuperar.setText(ocupado ? "Comprobando…" : "Continuar cambio");
    }

    public void limpiarContrasena() {
        contrasena.clear();
    }
}
