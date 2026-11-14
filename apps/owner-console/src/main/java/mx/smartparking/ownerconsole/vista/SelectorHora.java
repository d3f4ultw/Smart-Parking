package mx.smartparking.ownerconsole.vista;

import java.net.URL;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.Optional;
import javafx.geometry.Pos;
import javafx.scene.Cursor;
import javafx.scene.control.Button;
import javafx.scene.control.ButtonBar;
import javafx.scene.control.ButtonType;
import javafx.scene.control.Dialog;
import javafx.scene.control.DialogPane;
import javafx.scene.control.Label;
import javafx.scene.control.TextField;
import javafx.scene.input.MouseEvent;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Pane;
import javafx.scene.layout.Priority;
import javafx.scene.layout.VBox;
import javafx.scene.shape.Circle;
import javafx.scene.shape.Line;
import javafx.stage.Window;

/** Campo de hora con un selector de reloj interactivo en formato de 24 horas. */
public final class SelectorHora extends HBox {

    private static final DateTimeFormatter FORMATO_HORA = DateTimeFormatter.ofPattern("HH:mm");
    private static final ButtonType ACEPTAR = new ButtonType("Aceptar", ButtonBar.ButtonData.OK_DONE);
    private static final ButtonType CANCELAR = new ButtonType("Cancelar", ButtonBar.ButtonData.CANCEL_CLOSE);

    private final TextField campo;
    private final String etiqueta;

    public SelectorHora(TextField campo, String etiqueta) {
        this.campo = campo;
        this.etiqueta = etiqueta;
        setAlignment(Pos.CENTER_LEFT);
        getStyleClass().add("selector-hora");

        campo.setPrefHeight(36);
        campo.setMaxWidth(Double.MAX_VALUE);
        campo.setEditable(false);
        campo.setCursor(Cursor.HAND);
        campo.setAccessibleText(etiqueta);
        campo.setAccessibleHelp("Campo de solo lectura. Haz clic para abrir el selector y elegir la hora.");
        campo.setOnMouseClicked(evento -> abrirSelector());
        campo.setOnAction(evento -> abrirSelector());
        HBox.setHgrow(campo, Priority.ALWAYS);
        getChildren().setAll(campo);
    }

    private void abrirSelector() {
        LocalTime inicial;
        try {
            inicial = LocalTime.parse(campo.getText().trim());
        } catch (DateTimeParseException | NullPointerException ignorado) {
            inicial = LocalTime.of(9, 0);
        }

        Dialog<LocalTime> dialogo = new Dialog<>();
        Window propietario = getScene() == null ? null : getScene().getWindow();
        if (propietario != null) {
            dialogo.initOwner(propietario);
        }
        dialogo.setTitle("Hora de " + etiqueta.toLowerCase());
        dialogo.setResizable(false);

        Button horaDigital = new Button();
        Button minutoDigital = new Button();
        Button antesDelMediodia = new Button("a. m.");
        Button despuesDelMediodia = new Button("p. m.");
        horaDigital.getStyleClass().add("reloj-digital");
        minutoDigital.getStyleClass().add("reloj-digital");
        horaDigital.setAccessibleText("Hora seleccionada");
        minutoDigital.setAccessibleText("Minutos seleccionados");
        antesDelMediodia.getStyleClass().add("reloj-periodo");
        despuesDelMediodia.getStyleClass().add("reloj-periodo");
        HBox periodo = new HBox(2, antesDelMediodia, despuesDelMediodia);
        periodo.setAlignment(Pos.CENTER);
        Label separador = new Label(":");
        separador.getStyleClass().add("reloj-separador");
        HBox pantalla = new HBox(6, horaDigital, separador, minutoDigital, periodo);
        pantalla.setAlignment(Pos.CENTER);
        CaraReloj cara = new CaraReloj(inicial);
        horaDigital.setOnAction(evento -> {
            cara.seleccionarHora();
            horaDigital.requestFocus();
        });
        minutoDigital.setOnAction(evento -> {
            cara.seleccionarMinuto();
            minutoDigital.requestFocus();
        });
        antesDelMediodia.setAccessibleText("Seleccionar antes del mediodía");
        despuesDelMediodia.setAccessibleText("Seleccionar después del mediodía");
        antesDelMediodia.setOnAction(evento -> cara.seleccionarPeriodo(false));
        despuesDelMediodia.setOnAction(evento -> cara.seleccionarPeriodo(true));
        cara.setAlCambiar(() -> {
            horaDigital.setText(String.format("%02d", cara.horaEnEsfera()));
            minutoDigital.setText(String.format("%02d", cara.minuto()));
            marcarSeleccion(horaDigital, cara.seleccionandoHora());
            marcarSeleccion(minutoDigital, !cara.seleccionandoHora());
            marcarSeleccion(antesDelMediodia, !cara.esDespuesDelMediodia());
            marcarSeleccion(despuesDelMediodia, cara.esDespuesDelMediodia());
        });
        cara.actualizar();

        VBox contenido = new VBox(12, pantalla, cara);
        contenido.setAlignment(Pos.CENTER);
        contenido.getStyleClass().add("reloj-picker");

        DialogPane panel = dialogo.getDialogPane();
        panel.getButtonTypes().setAll(CANCELAR, ACEPTAR);
        panel.setContent(contenido);
        panel.setPrefWidth(340);
        URL hojaEstilos = SelectorHora.class.getResource("/mx/smartparking/ownerconsole/estilos.css");
        if (hojaEstilos != null) {
            panel.getStylesheets().add(hojaEstilos.toExternalForm());
        }
        dialogo.setResultConverter(tipo -> tipo == ACEPTAR
                ? LocalTime.of(cara.hora(), cara.minuto())
                : null);
        Optional<LocalTime> seleccion = dialogo.showAndWait();
        seleccion.ifPresent(hora -> campo.setText(FORMATO_HORA.format(hora)));
    }

    private static void marcarSeleccion(Button boton, boolean seleccionado) {
        boton.getStyleClass().remove("reloj-digital-activo");
        if (seleccionado) {
            boton.getStyleClass().add("reloj-digital-activo");
        }
    }

    private static final class CaraReloj extends Pane {

        private static final double CENTRO = 140;
        private static final double RADIO_EXTERIOR = 104;
        private final Circle fondo = new Circle(CENTRO, CENTRO, 132);
        private final Line aguja = new Line(CENTRO, CENTRO, CENTRO, CENTRO - RADIO_EXTERIOR);
        private final Circle punta = new Circle(CENTRO, CENTRO - RADIO_EXTERIOR, 9);
        private final Circle pivote = new Circle(CENTRO, CENTRO, 4);
        private int hora;
        private int minuto;
        private boolean seleccionandoHora;
        private Runnable alCambiar = () -> { };

        CaraReloj(LocalTime inicial) {
            hora = inicial.getHour();
            minuto = inicial.getMinute();
            seleccionandoHora = true;
            setMinSize(280, 280);
            setPrefSize(280, 280);
            setMaxSize(280, 280);
            setFocusTraversable(true);

            fondo.getStyleClass().add("reloj-cara");
            aguja.getStyleClass().add("reloj-aguja");
            punta.getStyleClass().add("reloj-punta");
            pivote.getStyleClass().add("reloj-pivote");
            getChildren().setAll(fondo, aguja, punta, pivote);
            setOnMousePressed(this::seleccionarDesdePosicion);
            setOnMouseDragged(this::seleccionarDesdePosicion);
            setOnMouseReleased(evento -> {
                if (seleccionandoHora) {
                    seleccionandoHora = false;
                    actualizar();
                }
            });
        }

        int hora() {
            return hora;
        }

        int minuto() {
            return minuto;
        }

        int horaEnEsfera() {
            int hora12 = hora % 12;
            return hora12 == 0 ? 12 : hora12;
        }

        boolean esDespuesDelMediodia() {
            return hora >= 12;
        }

        boolean seleccionandoHora() {
            return seleccionandoHora;
        }

        void setAlCambiar(Runnable alCambiar) {
            this.alCambiar = alCambiar == null ? () -> { } : alCambiar;
        }

        void seleccionarHora() {
            seleccionandoHora = true;
            actualizar();
        }

        void seleccionarMinuto() {
            seleccionandoHora = false;
            actualizar();
        }

        void seleccionarPeriodo(boolean despuesDelMediodia) {
            hora = hora % 12 + (despuesDelMediodia ? 12 : 0);
            actualizar();
        }

        void actualizar() {
            getChildren().removeIf(Button.class::isInstance);
            double angulo = seleccionandoHora ? (horaEnEsfera() % 12) * 30.0 - 90.0 : minuto * 6.0 - 90.0;
            double radio = RADIO_EXTERIOR;
            colocarAguja(angulo, radio);
            if (seleccionandoHora) {
                for (int valor = 1; valor <= 12; valor++) {
                    int horaDial = valor;
                    agregarNumero(
                            String.format("%02d", horaDial),
                            horaDial % 12 * 30.0 - 90.0,
                            RADIO_EXTERIOR,
                            horaDial == horaEnEsfera(),
                            () -> {
                                hora = horaDial % 12 + (hora >= 12 ? 12 : 0);
                                seleccionandoHora = false;
                                actualizar();
                            });
                }
            } else {
                for (int valor = 0; valor < 60; valor += 5) {
                    int minutoDial = valor;
                    agregarNumero(
                            String.format("%02d", valor),
                            valor * 6.0 - 90.0,
                            RADIO_EXTERIOR,
                            valor == minuto,
                            () -> {
                                minuto = minutoDial;
                                actualizar();
                            });
                }
            }
            alCambiar.run();
        }

        private void agregarNumero(
                String texto,
                double angulo,
                double radio,
                boolean seleccionado,
                Runnable alSeleccionar) {
            double radianes = Math.toRadians(angulo);
            double x = CENTRO + Math.cos(radianes) * radio;
            double y = CENTRO + Math.sin(radianes) * radio;
            Button numero = new Button(texto);
            numero.setMinSize(36, 36);
            numero.setPrefSize(36, 36);
            numero.setMaxSize(36, 36);
            numero.setAccessibleText(texto + (seleccionandoHora ? " horas" : " minutos"));
            numero.getStyleClass().add("reloj-numero");
            if (seleccionado) {
                numero.getStyleClass().add("reloj-numero-seleccionado");
            }
            numero.setOnAction(evento -> alSeleccionar.run());
            numero.relocate(x - 18, y - 18);
            getChildren().add(numero);
        }

        private void colocarAguja(double angulo, double radio) {
            double radianes = Math.toRadians(angulo);
            double x = CENTRO + Math.cos(radianes) * radio;
            double y = CENTRO + Math.sin(radianes) * radio;
            aguja.setEndX(x);
            aguja.setEndY(y);
            punta.setCenterX(x);
            punta.setCenterY(y);
        }

        private void seleccionarDesdePosicion(MouseEvent evento) {
            double dx = evento.getX() - CENTRO;
            double dy = evento.getY() - CENTRO;
            double distancia = Math.hypot(dx, dy);
            if (distancia < 25 || distancia > RADIO_EXTERIOR + 26) {
                return;
            }
            double grados = (Math.toDegrees(Math.atan2(dy, dx)) + 450) % 360;
            if (seleccionandoHora) {
                int valor = ((int) Math.round(grados / 30.0)) % 12;
                hora = valor + (hora >= 12 ? 12 : 0);
            } else {
                minuto = ((int) Math.round(grados / 6.0)) % 60;
            }
            actualizar();
            evento.consume();
        }
    }
}
