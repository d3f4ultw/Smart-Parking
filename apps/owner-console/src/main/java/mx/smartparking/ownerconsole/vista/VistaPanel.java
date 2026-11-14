package mx.smartparking.ownerconsole.vista;

import java.util.function.Consumer;
import javafx.animation.PauseTransition;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.PasswordField;
import javafx.scene.control.Separator;
import javafx.scene.control.TextField;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.Region;
import javafx.scene.layout.StackPane;
import javafx.scene.layout.VBox;
import javafx.util.Duration;
import mx.smartparking.ownerconsole.modelo.DatosPanel;
import mx.smartparking.ownerconsole.modelo.EdicionEstacionamiento;

/** Panel del propietario y edición de los datos del estacionamiento. */
public final class VistaPanel extends BorderPane {

    private final Label propietario = new Label();
    private final Label correo = new Label();
    private final Label nombreEstacionamiento = new Label();
    private final Label tipoEstacionamiento = new Label();
    private final Label horario = new Label();
    private final Label zonaHoraria = new Label();
    private final Label estado = VistaComun.crearMensajeEstado();
    private final Label errorNombre = new Label();
    private final Label errorAdministrativa = new Label();
    private final TextField nuevoNombre = new TextField();
    private final PasswordField contrasenaAdministrativa = new PasswordField();
    private final Button cambiarNombre = new Button("✎  Cambiar nombre");
    private final Button editarDatosEstacionamiento = new Button("Editar tipo y horario");
    private final Button guardarNombre = new Button("Guardar nombre");
    private final Button cancelarNombre = new Button("Cancelar");
    private final Button reemplazar = new Button("Cambiar propietario");
    private final Button salir = new Button("Cerrar sesión");
    private PauseTransition temporizadorEstado;
    private DatosPanel datosPanel;

    public VistaPanel(
            Consumer<String> alRenombrar,
            Consumer<EdicionEstacionamiento> alActualizarEstacionamiento,
            Runnable alIniciarTransferencia,
            Runnable alSalir) {
        BorderPane marco = VistaComun.crearMarco("Panel del propietario");
        if (marco.getTop() instanceof VBox encabezado) {
            encabezado.setPadding(new Insets(8, 0, 12, 0));
        }
        marco.setPadding(new Insets(22, 20, 12, 20));
        propietario.getStyleClass().add("title-2");
        propietario.setWrapText(true);
        correo.getStyleClass().add("text-muted");
        nombreEstacionamiento.getStyleClass().add("nombre-estacionamiento-panel");
        tipoEstacionamiento.getStyleClass().add("panel-dato-valor");
        horario.getStyleClass().add("panel-dato-valor");
        zonaHoraria.getStyleClass().add("panel-dato-valor");

        VBox identidadPropietario = new VBox(2, propietario, correo);
        VBox tarjetaEstacionamiento = VistaComun.crearTarjeta();
        tarjetaEstacionamiento.setPadding(new Insets(12));
        tarjetaEstacionamiento.setSpacing(8);
        Label tituloEstacionamiento = new Label("Estacionamiento");
        tituloEstacionamiento.getStyleClass().add("title-3");
        nuevoNombre.setPromptText("Nombre del estacionamiento");
        nuevoNombre.setPrefHeight(38);
        nuevoNombre.textProperty().addListener(
                (observable, anterior, nuevo) -> errorNombre.setText(""));
        errorNombre.getStyleClass().add("error-campo");
        errorNombre.setWrapText(true);
        errorNombre.setVisible(false);
        errorNombre.setManaged(false);
        errorNombre.textProperty().addListener((observable, anterior, nuevo) -> {
            boolean visible = nuevo != null && !nuevo.isBlank();
            errorNombre.setVisible(visible);
            errorNombre.setManaged(visible);
        });
        guardarNombre.getStyleClass().add("accent");
        guardarNombre.setText("Guardar");
        guardarNombre.setMinWidth(Region.USE_PREF_SIZE);
        guardarNombre.setOnAction(evento -> alRenombrar.accept(nuevoNombre.getText().trim()));
        cancelarNombre.getStyleClass().add("flat");
        cancelarNombre.setMinWidth(Region.USE_PREF_SIZE);
        cancelarNombre.setOnAction(evento -> mostrarEdicionNombre(false));
        editarDatosEstacionamiento.getStyleClass().add("boton-cerrar-sesion");
        editarDatosEstacionamiento.setOnAction(evento -> abrirEditorDatosEstacionamiento(alActualizarEstacionamiento));
        cambiarNombre.getStyleClass().add("boton-cerrar-sesion");
        cambiarNombre.setMinWidth(Region.USE_PREF_SIZE);
        cambiarNombre.setOnAction(evento -> {
            nuevoNombre.setText(nombreEstacionamiento.getText());
            mostrarEdicionNombre(true);
            nuevoNombre.requestFocus();
            nuevoNombre.selectAll();
        });
        StackPane valorNombreEstacionamiento = new StackPane(nombreEstacionamiento, nuevoNombre);
        valorNombreEstacionamiento.setMinHeight(40);
        valorNombreEstacionamiento.setPrefHeight(40);
        valorNombreEstacionamiento.setMaxHeight(40);
        valorNombreEstacionamiento.getStyleClass().add("editor-nombre-panel");
        nombreEstacionamiento.setAlignment(Pos.CENTER_LEFT);
        VBox encabezadoEstacionamiento = new VBox(2, tituloEstacionamiento, valorNombreEstacionamiento);
        HBox accionesNombre = new HBox(6, cambiarNombre, guardarNombre, cancelarNombre);
        accionesNombre.setMinWidth(200);
        accionesNombre.setPrefWidth(200);
        accionesNombre.setMaxWidth(200);
        accionesNombre.setAlignment(Pos.CENTER_RIGHT);
        HBox filaNombre = new HBox(12, encabezadoEstacionamiento, accionesNombre);
        filaNombre.setAlignment(Pos.CENTER_LEFT);
        HBox.setHgrow(encabezadoEstacionamiento, Priority.ALWAYS);
        VBox bloqueNombre = new VBox(2, filaNombre, errorNombre);
        bloqueNombre.getStyleClass().add("editor-nombre-panel");

        VBox datoTipo = crearDato("Tipo", tipoEstacionamiento);
        VBox datoHorario = crearDato("Horario", horario);
        HBox.setHgrow(datoTipo, Priority.ALWAYS);
        HBox.setHgrow(datoHorario, Priority.ALWAYS);
        HBox datosPrincipales = new HBox(16, datoTipo, datoHorario);
        HBox accionesDatos = new HBox(VistaComun.separadorFlexible(), editarDatosEstacionamiento);
        accionesDatos.setAlignment(Pos.CENTER_RIGHT);
        VBox datosEstacionamiento = new VBox(8,
                datosPrincipales, crearDato("Zona horaria", zonaHoraria), accionesDatos);
        Separator separador = new Separator();
        separador.getStyleClass().add("separador-estacionamiento-panel");
        tarjetaEstacionamiento.getChildren().addAll(
                bloqueNombre, separador, datosEstacionamiento);
        mostrarEdicionNombre(false);

        VBox tarjetaTransferencia = VistaComun.crearTarjeta();
        tarjetaTransferencia.getStyleClass().add("tarjeta-riesgo");
        tarjetaTransferencia.setPadding(new Insets(14));
        tarjetaTransferencia.setSpacing(10);
        Label tituloTransferencia = new Label("Cambiar propietario");
        tituloTransferencia.getStyleClass().add("title-3");
        Label aviso = new Label(
                "Al continuar, el propietario actual perderá el acceso. "
                        + "Después tendrás que completar de nuevo la configuración. "
                        + "Si sales antes de terminar, podrás continuar con la contraseña anterior de administración.");
        aviso.setWrapText(true);
        aviso.getStyleClass().add("text-muted");
        contrasenaAdministrativa.setPromptText("Contraseña de administración");
        contrasenaAdministrativa.setPrefHeight(42);
        contrasenaAdministrativa.textProperty().addListener(
                (observable, anterior, nuevo) -> errorAdministrativa.setText(""));
        errorAdministrativa.getStyleClass().add("error-campo");
        errorAdministrativa.setWrapText(true);
        reemplazar.getStyleClass().add("danger");
        reemplazar.setOnAction(evento -> alIniciarTransferencia.run());
        tarjetaTransferencia.getChildren().addAll(
                tituloTransferencia,
                aviso,
                VistaComun.crearCampo("Contraseña de administración", contrasenaAdministrativa, null, errorAdministrativa),
                reemplazar);

        VBox contenido = new VBox(8,
                identidadPropietario, tarjetaEstacionamiento, estado);
        contenido.setMaxWidth(680);
        contenido.setFillWidth(true);
        marco.setCenter(contenido);
        salir.getStyleClass().remove("flat");
        salir.getStyleClass().add("boton-cerrar-sesion");
        salir.setMinWidth(144);
        salir.setOnAction(evento -> alSalir.run());
        HBox barra = new HBox(VistaComun.separadorFlexible(), salir);
        barra.setAlignment(Pos.CENTER_RIGHT);
        marco.setBottom(barra);
        setTop(marco.getTop());
        setCenter(marco.getCenter());
        setBottom(marco.getBottom());
        setPadding(marco.getPadding());
        estado.setMinHeight(0);
        getStyleClass().add("fondo-aplicacion");
    }

    public void mostrarPanel(DatosPanel panel) {
        datosPanel = panel;
        propietario.setText(panel.propietario().nombreCompleto());
        correo.setText(panel.propietario().correo());
        nombreEstacionamiento.setText(panel.estacionamiento().nombre());
        nuevoNombre.setText(panel.estacionamiento().nombre());
        tipoEstacionamiento.setText(etiquetaTipo(panel.estacionamiento().tipo()));
        DatosPanel.Horario horarioPanel = panel.estacionamiento().horario();
        horario.setText("CONTINUO_24_7".equals(horarioPanel.modo())
                ? "Abierto todo el día"
                : horarioPanel.horaApertura() + " – " + horarioPanel.horaCierre());
        zonaHoraria.setText(etiquetaZonaHoraria(horarioPanel.zonaHoraria()));
        errorNombre.setText("");
        mostrarEdicionNombre(false);
    }

    public void mostrarEstado(String texto, boolean ocupado) {
        detenerTemporizadorEstado();
        estado.setText(texto == null ? "" : texto);
        setDisable(ocupado);
        guardarNombre.setDisable(ocupado);
        cancelarNombre.setDisable(ocupado);
        cambiarNombre.setDisable(ocupado);
        editarDatosEstacionamiento.setDisable(ocupado);
        reemplazar.setDisable(ocupado);
        salir.setDisable(ocupado);
        guardarNombre.setText(ocupado ? "Guardando…" : "Guardar");
        reemplazar.setText(ocupado ? "Comprobando…" : "Cambiar propietario");
    }

    public void mostrarAvisoTemporal(String texto) {
        mostrarEstado(texto, false);
        temporizadorEstado = new PauseTransition(Duration.seconds(1.5));
        temporizadorEstado.setOnFinished(evento -> {
            estado.setText("");
            temporizadorEstado = null;
        });
        temporizadorEstado.playFromStart();
    }

    public void mostrarErrorNombre(String texto) {
        mostrarEdicionNombre(true);
        errorNombre.setText(texto);
    }

    public void limpiarContrasenaAdministrativa() {
        contrasenaAdministrativa.clear();
    }

    public String leerContrasenaAdministrativa() {
        return contrasenaAdministrativa.getText();
    }

    public void mostrarErrorAdministrativo(String texto) {
        errorAdministrativa.setText(texto);
    }

    public void mostrarAvisoCorreo(String estadoCorreo, String accion) {
        if (estadoCorreo == null || estadoCorreo.isBlank()) {
            return;
        }
        detenerTemporizadorEstado();
        String mensaje = switch (estadoCorreo) {
            case "ENVIADO" -> "El cambio quedó guardado y el aviso se envió.";
            case "FALLIDO" -> "El cambio quedó guardado, pero no pudimos enviar el aviso.";
            case "DESHABILITADO" -> "El cambio quedó guardado. No se pudo enviar el aviso.";
            case "DESCONOCIDO" -> "El cambio quedó guardado, pero no pudimos saber si enviamos el aviso.";
            default -> "El cambio quedó guardado.";
        };
        estado.setText(mensaje);
    }

    private void detenerTemporizadorEstado() {
        if (temporizadorEstado != null) {
            temporizadorEstado.stop();
            temporizadorEstado = null;
        }
    }

    private void abrirEditorDatosEstacionamiento(Consumer<EdicionEstacionamiento> alActualizar) {
        if (datosPanel == null) {
            return;
        }
        new VistaEdicionEstacionamiento(getScene().getWindow(), datosPanel.estacionamiento())
                .showAndWait()
                .ifPresent(alActualizar);
    }

    private String etiquetaTipo(String tipo) {
        return switch (tipo) {
            case "PUBLICO" -> "Público";
            case "PRIVADO" -> "Privado";
            case "MIXTO" -> "Mixto";
            default -> tipo;
        };
    }

    private VBox crearDato(String etiqueta, Label valor) {
        Label titulo = new Label(etiqueta);
        titulo.getStyleClass().add("panel-dato-etiqueta");
        VBox dato = new VBox(4, titulo, valor);
        dato.setMaxWidth(Double.MAX_VALUE);
        return dato;
    }

    private String etiquetaZonaHoraria(String identificador) {
        if (identificador == null || identificador.isBlank()) {
            return "";
        }
        if ("America/Mexico_City".equals(identificador)) {
            return "Ciudad de México";
        }
        int separador = identificador.lastIndexOf('/');
        String ciudad = separador >= 0 ? identificador.substring(separador + 1) : identificador;
        return ciudad.replace('_', ' ');
    }

    private void mostrarEdicionNombre(boolean visible) {
        nombreEstacionamiento.setVisible(!visible);
        nombreEstacionamiento.setManaged(!visible);
        nuevoNombre.setVisible(visible);
        nuevoNombre.setManaged(visible);
        guardarNombre.setVisible(visible);
        guardarNombre.setManaged(visible);
        cancelarNombre.setVisible(visible);
        cancelarNombre.setManaged(visible);
        cambiarNombre.setVisible(!visible);
        cambiarNombre.setManaged(!visible);
        if (!visible) {
            errorNombre.setText("");
        }
    }

}
