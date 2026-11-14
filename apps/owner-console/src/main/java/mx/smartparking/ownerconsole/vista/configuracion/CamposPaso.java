package mx.smartparking.ownerconsole.vista.configuracion;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import javafx.scene.Node;
import javafx.scene.control.ComboBox;
import javafx.scene.control.Control;
import javafx.scene.control.Label;
import javafx.scene.control.TextField;
import javafx.scene.layout.Region;
import javafx.scene.layout.VBox;
import mx.smartparking.ownerconsole.vista.VistaComun;

/** Construye grupos de campos con el mismo tratamiento de errores y foco. */
final class CamposPaso {

    private final VBox contenido = new VBox(15);
    private final Map<String, Campo> campos = new LinkedHashMap<>();

    CamposPaso(String titulo, String descripcion) {
        Label encabezado = new Label(titulo);
        encabezado.getStyleClass().add("title-2");
        encabezado.setWrapText(true);
        encabezado.setMaxWidth(Double.MAX_VALUE);
        contenido.getChildren().add(encabezado);
        if (descripcion != null && !descripcion.isBlank()) {
            Label explicacion = new Label(descripcion);
            explicacion.getStyleClass().add("text-muted");
            explicacion.setWrapText(true);
            contenido.getChildren().add(explicacion);
        }
        contenido.setFillWidth(true);
        contenido.setPadding(new javafx.geometry.Insets(2, 0, 0, 0));
    }

    VBox contenido() {
        return contenido;
    }

    void agregarContenido(Node nodo) {
        contenido.getChildren().add(nodo);
    }

    void agregarCampo(String clave, String etiqueta, Control control, String ayuda) {
        agregarCampoInterno(clave, etiqueta, control, control, null, ayuda, null);
    }

    void agregarGrupoOpciones(String clave, String etiqueta, Node grupo, Control controlEnfocable) {
        Label error = new Label();
        VBox campo = VistaComun.crearCampo(etiqueta, grupo, null, error);
        campo.setSpacing(8);
        contenido.getChildren().add(campo);
        campos.put(clave, new Campo(controlEnfocable, null, error, grupo));
    }

    void agregarCampoConIndicador(
            String clave,
            String etiqueta,
            Node controlVisual,
            Control control,
            TextField controlVisible,
            String ayuda,
            Node indicador) {
        agregarCampoInterno(clave, etiqueta, controlVisual, control, controlVisible, ayuda, indicador);
    }

    private void agregarCampoInterno(
            String clave,
            String etiqueta,
            Node controlVisual,
            Control control,
            TextField controlVisible,
            String ayuda,
            Node indicador) {
        control.setPrefHeight(36);
        control.setMaxWidth(Double.MAX_VALUE);
        if (controlVisual instanceof Region region) {
            region.setPrefHeight(36);
            region.setMaxWidth(Double.MAX_VALUE);
        }
        Label error = new Label();
        VBox campo = VistaComun.crearCampo(etiqueta, controlVisual, ayuda, error);
        campo.setSpacing(8);
        if (indicador != null) {
            campo.getChildren().add(indicador);
        }
        contenido.getChildren().add(campo);
        campos.put(clave, new Campo(control, controlVisible, error, null));
        if (control instanceof TextField texto) {
            texto.textProperty().addListener((observable, anterior, actual) -> limpiarError(clave));
        } else if (control instanceof ComboBox<?> combo) {
            combo.valueProperty().addListener((observable, anterior, actual) -> limpiarError(clave));
        }
    }

    void mostrarErrores(Map<String, String> errores) {
        mostrarErrores(errores, Set.of());
    }

    void mostrarErrores(Map<String, String> errores, Set<String> mensajesOcultos) {
        limpiarErrores();
        Control primerControlInvalido = null;
        for (Map.Entry<String, Campo> entrada : campos.entrySet()) {
            String mensaje = errores.get(entrada.getKey());
            if (mensaje == null) {
                continue;
            }
            Campo campo = entrada.getValue();
            campo.error().setText(mensajesOcultos.contains(entrada.getKey()) ? "" : mensaje);
            if (campo.grupoOpciones() == null) {
                campo.control().getStyleClass().add("campo-invalido");
            } else {
                campo.grupoOpciones().getStyleClass().add("campo-invalido");
            }
            TextField visible = campo.controlVisible();
            if (visible != null) {
                visible.getStyleClass().add("campo-invalido");
            }
            if (primerControlInvalido == null) {
                primerControlInvalido = visible != null && visible.isVisible() ? visible : campo.control();
            }
        }
        if (primerControlInvalido != null) {
            primerControlInvalido.requestFocus();
        }
    }

    void limpiarErrores() {
        campos.forEach((clave, campo) -> {
            campo.error().setText("");
            if (campo.grupoOpciones() == null) {
                campo.control().getStyleClass().remove("campo-invalido");
            } else {
                campo.grupoOpciones().getStyleClass().remove("campo-invalido");
            }
            if (campo.controlVisible() != null) {
                campo.controlVisible().getStyleClass().remove("campo-invalido");
            }
        });
    }

    void limpiarError(String clave) {
        Campo campo = campos.get(clave);
        if (campo == null) {
            return;
        }
        campo.error().setText("");
        if (campo.grupoOpciones() == null) {
            campo.control().getStyleClass().remove("campo-invalido");
        } else {
            campo.grupoOpciones().getStyleClass().remove("campo-invalido");
        }
        if (campo.controlVisible() != null) {
            campo.controlVisible().getStyleClass().remove("campo-invalido");
        }
    }

    private record Campo(Control control, TextField controlVisible, Label error, Node grupoOpciones) {
    }
}
