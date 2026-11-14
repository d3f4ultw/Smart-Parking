package mx.smartparking.ownerconsole.vista;

import java.util.function.BiConsumer;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.TextField;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.VBox;
import mx.smartparking.ownerconsole.vista.configuracion.ControlConOjo;

/** Inicio de sesión del único propietario activo. */
public final class VistaAcceso extends BorderPane {

    private static final String ERROR_CREDENCIALES = "Correo o contraseña incorrectos.";
    private final TextField correo = new TextField();
    private final ControlConOjo contrasena = new ControlConOjo("Contraseña", "la contraseña");
    private final Label errorCorreo = new Label();
    private final Label errorContrasena = new Label();
    private final Label mensaje = VistaComun.crearMensajeEstado();
    private final Button ingresar = new Button("Iniciar sesión");

    public VistaAcceso(BiConsumer<String, String> alIngresar) {
        BorderPane marco = VistaComun.crearMarco("");
        Label titulo = new Label("Bienvenido");
        titulo.getStyleClass().add("title-1");
        Label descripcion = new Label("Ingresa tus datos para continuar.");
        descripcion.getStyleClass().add("text-muted");
        correo.setPrefHeight(42);
        correo.setMaxWidth(Double.MAX_VALUE);
        contrasena.setPrefHeight(42);
        contrasena.setMaxWidth(Double.MAX_VALUE);
        contrasena.oculto().setPrefHeight(42);
        contrasena.oculto().setMaxWidth(Double.MAX_VALUE);
        contrasena.visible().setPrefHeight(42);
        contrasena.visible().setMaxWidth(Double.MAX_VALUE);
        correo.textProperty().addListener((observable, anterior, actual) -> {
            limpiarError(correo, errorCorreo);
            limpiarMensajeCredenciales();
        });
        contrasena.oculto().textProperty().addListener((observable, anterior, actual) -> {
            limpiarErrorContrasena();
            limpiarMensajeCredenciales();
        });
        ingresar.getStyleClass().add("accent");
        ingresar.setDefaultButton(true);
        ingresar.setOnAction(evento -> alIngresar.accept(correo.getText().trim(), contrasena.oculto().getText()));
        VBox tarjeta = VistaComun.crearTarjeta();
        tarjeta.getChildren().addAll(
                titulo,
                descripcion,
                VistaComun.crearCampo("Correo electrónico", correo, null, errorCorreo),
                VistaComun.crearCampo("Contraseña", contrasena, null, errorContrasena),
                mensaje,
                ingresar);
        tarjeta.setAlignment(Pos.CENTER_LEFT);
        marco.setCenter(tarjeta);
        setTop(marco.getTop());
        setCenter(marco.getCenter());
        setPadding(marco.getPadding());
        getStyleClass().add("fondo-aplicacion");
    }

    public void mostrarEstado(String texto, boolean ocupado) {
        mensaje.getStyleClass().remove("error-campo");
        mensaje.setText(texto == null ? "" : texto);
        setDisable(ocupado);
        ingresar.setDisable(ocupado);
        ingresar.setText(ocupado ? "Comprobando…" : "Iniciar sesión");
    }

    public void mostrarErrores(String textoErrorCorreo, String textoErrorContrasena) {
        mensaje.getStyleClass().remove("error-campo");
        mensaje.setText("");
        establecerError(correo, errorCorreo, textoErrorCorreo);
        establecerErrorContrasena(textoErrorContrasena);
        if (textoErrorCorreo != null && !textoErrorCorreo.isBlank()) {
            correo.requestFocus();
        } else if (textoErrorContrasena != null && !textoErrorContrasena.isBlank()) {
            contrasena.enfocar();
        }
    }

    public void mostrarErrorCredenciales() {
        mostrarEstado("", false);
        mensaje.setText(ERROR_CREDENCIALES);
        if (!mensaje.getStyleClass().contains("error-campo")) {
            mensaje.getStyleClass().add("error-campo");
        }
    }

    public void limpiarContrasena() {
        contrasena.limpiar();
    }

    public void enfocarCorreo() {
        correo.requestFocus();
    }

    private void establecerError(TextField campo, Label etiquetaError, String texto) {
        String error = texto == null ? "" : texto;
        etiquetaError.setText(error);
        if (error.isBlank()) {
            campo.getStyleClass().remove("campo-invalido");
        } else if (!campo.getStyleClass().contains("campo-invalido")) {
            campo.getStyleClass().add("campo-invalido");
        }
    }

    private void limpiarError(TextField campo, Label etiquetaError) {
        etiquetaError.setText("");
        campo.getStyleClass().remove("campo-invalido");
    }

    private void establecerErrorContrasena(String texto) {
        establecerError(contrasena.oculto(), errorContrasena, texto);
        establecerError(contrasena.visible(), errorContrasena, texto);
    }

    private void limpiarErrorContrasena() {
        limpiarError(contrasena.oculto(), errorContrasena);
        contrasena.visible().getStyleClass().remove("campo-invalido");
    }

    private void limpiarMensajeCredenciales() {
        if (ERROR_CREDENCIALES.equals(mensaje.getText())) {
            mensaje.setText("");
            mensaje.getStyleClass().remove("error-campo");
        }
    }
}
