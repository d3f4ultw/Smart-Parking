package mx.smartparking.ownerconsole.vista;

import java.net.URL;
import java.time.LocalTime;
import java.time.ZoneId;
import javafx.event.ActionEvent;
import javafx.scene.Node;
import javafx.scene.control.Button;
import javafx.scene.control.ButtonBar;
import javafx.scene.control.ButtonType;
import javafx.scene.control.ComboBox;
import javafx.scene.control.Dialog;
import javafx.scene.control.DialogPane;
import javafx.scene.control.Label;
import javafx.scene.control.RadioButton;
import javafx.scene.control.TextField;
import javafx.scene.control.ToggleGroup;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.VBox;
import javafx.stage.Window;
import mx.smartparking.ownerconsole.modelo.DatosPanel;
import mx.smartparking.ownerconsole.modelo.EdicionEstacionamiento;
import mx.smartparking.ownerconsole.vista.configuracion.SelectorZonaHoraria;

/** Diálogo para editar el tipo, el horario y la zona del estacionamiento. */
final class VistaEdicionEstacionamiento extends Dialog<EdicionEstacionamiento> {

    VistaEdicionEstacionamiento(Window propietario, DatosPanel.Estacionamiento estacionamiento) {
        setTitle("Editar tipo y horario");
        setResizable(false);
        if (propietario != null) {
            initOwner(propietario);
        }

        ComboBox<TipoOpcion> tipo = crearSelectorTipo(estacionamiento.tipo());
        RadioButton continuo = new RadioButton("Abierto las 24 horas");
        RadioButton intervalo = new RadioButton("Horario fijo todos los días");
        ToggleGroup grupoHorario = new ToggleGroup();
        continuo.setToggleGroup(grupoHorario);
        intervalo.setToggleGroup(grupoHorario);
        continuo.setSelected("CONTINUO_24_7".equals(estacionamiento.horario().modo()));
        intervalo.setSelected(!continuo.isSelected());
        VBox opcionesHorario = new VBox(5, new Label("Horario"), new HBox(14, continuo, intervalo));

        SelectorZonaHoraria zona = new SelectorZonaHoraria();
        zona.setText(estacionamiento.horario().zonaHoraria());
        zona.setPrefHeight(36);
        TextField apertura = new TextField(horaInicial(estacionamiento.horario().horaApertura(), "09:00"));
        TextField cierre = new TextField(horaInicial(estacionamiento.horario().horaCierre(), "18:00"));
        SelectorHora selectorApertura = new SelectorHora(apertura, "Apertura");
        SelectorHora selectorCierre = new SelectorHora(cierre, "Cierre");
        selectorApertura.disableProperty().bind(continuo.selectedProperty());
        selectorCierre.disableProperty().bind(continuo.selectedProperty());
        VBox campoApertura = crearCampo("Apertura", selectorApertura);
        VBox campoCierre = crearCampo("Cierre", selectorCierre);
        HBox horas = new HBox(12, campoApertura, campoCierre);
        HBox.setHgrow(campoApertura, Priority.ALWAYS);
        HBox.setHgrow(campoCierre, Priority.ALWAYS);

        Label error = new Label();
        error.getStyleClass().add("error-campo");
        error.setWrapText(true);
        error.setVisible(false);
        error.setManaged(false);
        error.textProperty().addListener((observable, anterior, nuevo) -> {
            boolean visible = nuevo != null && !nuevo.isBlank();
            error.setVisible(visible);
            error.setManaged(visible);
        });

        VBox formulario = new VBox(10,
                crearCampo("Tipo de estacionamiento", tipo),
                opcionesHorario,
                crearCampo("Zona horaria", zona),
                horas,
                error);
        ButtonType guardar = new ButtonType("Guardar cambios", ButtonBar.ButtonData.OK_DONE);
        ButtonType cancelar = new ButtonType("Cancelar", ButtonBar.ButtonData.CANCEL_CLOSE);
        DialogPane panel = getDialogPane();
        panel.getButtonTypes().setAll(cancelar, guardar);
        panel.setContent(formulario);
        panel.setPrefWidth(460);
        URL hojaEstilos = getClass().getResource("/mx/smartparking/ownerconsole/estilos.css");
        if (hojaEstilos != null) {
            panel.getStylesheets().add(hojaEstilos.toExternalForm());
        }

        Button botonGuardar = (Button) panel.lookupButton(guardar);
        botonGuardar.addEventFilter(ActionEvent.ACTION, evento -> {
            String mensaje = validar(tipo.getValue(), continuo, intervalo, zona.getText(), apertura.getText(), cierre.getText());
            error.setText(mensaje == null ? "" : mensaje);
            if (mensaje != null) {
                evento.consume();
            }
        });
        setResultConverter(boton -> boton == guardar
                ? new EdicionEstacionamiento(
                        tipo.getValue().codigo(),
                        continuo.isSelected() ? "CONTINUO_24_7" : "INTERVALO_DIARIO",
                        zona.getText().trim(),
                        continuo.isSelected() ? null : apertura.getText().trim(),
                        continuo.isSelected() ? null : cierre.getText().trim())
                : null);
    }

    private ComboBox<TipoOpcion> crearSelectorTipo(String tipoActual) {
        ComboBox<TipoOpcion> tipo = new ComboBox<>();
        tipo.getItems().setAll(TipoOpcion.values());
        tipo.setMaxWidth(Double.MAX_VALUE);
        tipo.getItems().stream()
                .filter(opcion -> opcion.codigo().equals(tipoActual))
                .findFirst()
                .ifPresent(tipo::setValue);
        return tipo;
    }

    private VBox crearCampo(String etiqueta, Node control) {
        Label nombre = new Label(etiqueta);
        nombre.getStyleClass().add("label-campo");
        VBox campo = new VBox(4, nombre, control);
        campo.setMaxWidth(Double.MAX_VALUE);
        return campo;
    }

    private String validar(
            TipoOpcion tipo,
            RadioButton continuo,
            RadioButton intervalo,
            String zona,
            String apertura,
            String cierre) {
        if (tipo == null) {
            return "Selecciona un tipo de estacionamiento.";
        }
        if (!continuo.isSelected() && !intervalo.isSelected()) {
            return "Selecciona un horario de atención.";
        }
        if (zona == null || !ZoneId.getAvailableZoneIds().contains(zona.trim())) {
            return "Selecciona una zona horaria.";
        }
        if (intervalo.isSelected()) {
            String aperturaValidada = apertura == null ? "" : apertura.trim();
            String cierreValidada = cierre == null ? "" : cierre.trim();
            if (!aperturaValidada.matches("(?:[01][0-9]|2[0-3]):[0-5][0-9]")) {
                return "Selecciona una hora de apertura.";
            }
            if (!cierreValidada.matches("(?:[01][0-9]|2[0-3]):[0-5][0-9]")) {
                return "Selecciona una hora de cierre.";
            }
            if (LocalTime.parse(aperturaValidada).equals(LocalTime.parse(cierreValidada))) {
                return "La hora de cierre debe ser distinta de la apertura.";
            }
        }
        return null;
    }

    private String horaInicial(String valor, String predeterminada) {
        return valor == null ? predeterminada : valor;
    }

    private enum TipoOpcion {
        PUBLICO("PUBLICO", "Público"),
        PRIVADO("PRIVADO", "Privado"),
        MIXTO("MIXTO", "Mixto");

        private final String codigo;
        private final String etiqueta;

        TipoOpcion(String codigo, String etiqueta) {
            this.codigo = codigo;
            this.etiqueta = etiqueta;
        }

        String codigo() {
            return codigo;
        }

        @Override
        public String toString() {
            return etiqueta;
        }
    }
}
