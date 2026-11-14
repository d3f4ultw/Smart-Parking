package mx.smartparking.ownerconsole.vista.configuracion;

import javafx.geometry.Pos;
import javafx.scene.control.Label;
import javafx.scene.layout.HBox;

/** Indicador visual accesible que usa gris mientras no se cumple y lima al cumplirse. */
final class IndicadorContrasena extends HBox {

    private final Label punto = new Label("●");
    private final Label texto = new Label();

    IndicadorContrasena(String mensajePendiente) {
        punto.getStyleClass().addAll("indicador-punto", "indicador-pendiente");
        punto.setAccessibleText(mensajePendiente);
        texto.getStyleClass().add("texto-ayuda");
        texto.setText(mensajePendiente);
        setSpacing(6);
        setAlignment(Pos.CENTER_LEFT);
        getStyleClass().add("indicador-contrasena");
        getChildren().setAll(punto, texto);
    }

    void pendiente(String mensaje) {
        aplicar("indicador-pendiente", mensaje);
    }

    void valido(String mensaje) {
        aplicar("indicador-valido", mensaje);
    }

    private void aplicar(String clase, String mensaje) {
        punto.getStyleClass().removeAll("indicador-pendiente", "indicador-valido", "indicador-invalido");
        punto.getStyleClass().add(clase);
        punto.setAccessibleText(mensaje);
        texto.setText(mensaje);
    }
}
