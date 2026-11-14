package mx.smartparking.ownerconsole.vista.configuracion;

import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.PasswordField;
import javafx.scene.control.TextField;
import javafx.scene.control.ToggleButton;
import javafx.scene.layout.StackPane;
import javafx.scene.paint.Color;
import javafx.scene.shape.Circle;
import javafx.scene.shape.Line;
import javafx.scene.shape.SVGPath;

/** Campo de contraseña con alternancia de visibilidad y posición del cursor conservada. */
public final class ControlConOjo extends StackPane {

    private final PasswordField oculto = new PasswordField();
    private final TextField visible = new TextField();

    public ControlConOjo(String textoAccesible, String descripcionCampo) {
        oculto.textProperty().bindBidirectional(visible.textProperty());
        oculto.setAccessibleText(textoAccesible);
        visible.setAccessibleText(textoAccesible);
        visible.setVisible(false);

        SVGPath contorno = new SVGPath();
        contorno.setContent("M2 12 C4.5 7.5 8 5 12 5 C16 5 19.5 7.5 22 12 "
                + "C19.5 16.5 16 19 12 19 C8 19 4.5 16.5 2 12 Z");
        contorno.setFill(Color.TRANSPARENT);
        contorno.setStroke(Color.web("#5c6674"));
        contorno.setStrokeWidth(1.7);

        Circle pupila = new Circle(3);
        pupila.setFill(Color.TRANSPARENT);
        pupila.setStroke(Color.web("#5c6674"));
        pupila.setStrokeWidth(1.7);

        Line tachado = new Line(4, 20, 20, 4);
        tachado.setStroke(Color.web("#5c6674"));
        tachado.setStrokeWidth(1.7);
        tachado.setVisible(false);

        StackPane icono = new StackPane(contorno, pupila, tachado);
        icono.setPrefSize(22, 22);
        icono.setMouseTransparent(true);

        ToggleButton ojo = new ToggleButton();
        ojo.setGraphic(icono);
        ojo.getStyleClass().add("boton-ojo");
        ojo.setAccessibleText("Mostrar " + descripcionCampo);
        ojo.setAccessibleHelp("Muestra u oculta " + descripcionCampo + ".");
        ojo.setFocusTraversable(true);
        ojo.selectedProperty().addListener((observable, anterior, mostrar) -> {
            int posicion = mostrar ? oculto.getCaretPosition() : visible.getCaretPosition();
            oculto.setVisible(!mostrar);
            visible.setVisible(mostrar);
            tachado.setVisible(mostrar);
            ojo.setAccessibleText(mostrar ? "Ocultar " + descripcionCampo : "Mostrar " + descripcionCampo);
            if (mostrar) {
                visible.positionCaret(Math.min(posicion, visible.getLength()));
                visible.requestFocus();
            } else {
                oculto.positionCaret(Math.min(posicion, oculto.getLength()));
                oculto.requestFocus();
            }
        });
        StackPane.setAlignment(ojo, Pos.CENTER_RIGHT);
        StackPane.setMargin(ojo, new Insets(0, 4, 0, 0));

        getChildren().setAll(oculto, visible, ojo);
        getStyleClass().add("campo-con-ojo");
    }

    public PasswordField oculto() {
        return oculto;
    }

    public TextField visible() {
        return visible;
    }

    public void limpiar() {
        oculto.clear();
    }

    public void enfocar() {
        if (visible.isVisible()) {
            visible.requestFocus();
        } else {
            oculto.requestFocus();
        }
    }
}
