package mx.smartparking.ownerconsole.servicio;

import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import javafx.application.Platform;
import javafx.scene.Node;
import javafx.scene.Parent;
import javafx.scene.control.ButtonBase;
import javafx.scene.control.ComboBox;
import javafx.scene.control.Label;
import javafx.scene.control.PasswordField;
import javafx.scene.control.TextField;
import javafx.scene.control.ToggleButton;
import javafx.stage.Stage;
import javafx.stage.Window;
import mx.smartparking.ownerconsole.vista.SelectorHora;
import mx.smartparking.ownerconsole.vista.VistaPanel;
import mx.smartparking.ownerconsole.vista.configuracion.ControlConOjo;

/** Utilidades para las pruebas que disparan eventos JavaFX sin un robot de pantalla. */
final class JavaFxPropietarioTestSupport {

    static final Duration ESPERA_UI = Duration.ofSeconds(8);
    static final String CLAVE_ACCESO = "AccesoSeguro10";
    static final String CLAVE_ADMINISTRATIVA = "AdminSeguro10";

    private JavaFxPropietarioTestSupport() {
    }

    static void iniciarJavaFx() throws Exception {
        CountDownLatch iniciado = new CountDownLatch(1);
        Platform.startup(iniciado::countDown);
        assertTrue(iniciado.await(10, TimeUnit.SECONDS), "JavaFX debe iniciar para las pruebas de vista");
        Platform.setImplicitExit(false);
    }

    static void cerrarJavaFx() {
        Platform.exit();
    }

    static void abrirEditorYGuardar(VistaPanel panel, Stage escenario, boolean cambiarDatos) {
        java.util.concurrent.atomic.AtomicReference<Throwable> fallo = new java.util.concurrent.atomic.AtomicReference<>();
        Platform.runLater(() -> {
            try {
                Window dialogo = Window.getWindows().stream()
                        .filter(Window::isShowing)
                        .filter(ventana -> ventana instanceof Stage stage && stage.getOwner() == escenario)
                        .findFirst()
                        .orElseThrow(() -> new AssertionError("No se abrió el diálogo de edición"));
                Node raiz = dialogo.getScene().getRoot();
                if (cambiarDatos) {
                    ComboBox<?> selectorTipo = nodos(raiz).stream()
                            .filter(nodo -> nodo instanceof ComboBox<?>)
                            .map(nodo -> (ComboBox<?>) nodo)
                            .findFirst()
                            .orElseThrow(() -> new AssertionError("Falta el selector de tipo"));
                    int tipoActual = selectorTipo.getSelectionModel().getSelectedIndex();
                    selectorTipo.getSelectionModel().select(tipoActual == 0 ? 1 : 0);
                    List<SelectorHora> selectoresHora = nodos(raiz).stream()
                            .filter(SelectorHora.class::isInstance)
                            .map(SelectorHora.class::cast)
                            .toList();
                    assertTrue(selectoresHora.size() == 2, "El diálogo debe mostrar apertura y cierre");
                    campoDe(selectoresHora.get(0)).setText("22:00");
                    campoDe(selectoresHora.get(1)).setText("06:00");
                }
                boton(raiz, "Guardar cambios").fire();
            } catch (Throwable error) {
                fallo.set(error);
                Window.getWindows().stream()
                        .filter(Window::isShowing)
                        .filter(ventana -> ventana instanceof Stage stage && stage.getOwner() == escenario)
                        .findFirst()
                        .ifPresent(Window::hide);
            }
        });
        boton(panel, "Editar tipo y horario").fire();
        if (fallo.get() != null) {
            throw new AssertionError("Falló la interacción programática con el diálogo", fallo.get());
        }
    }

    static ButtonBase boton(Node raiz, String texto) {
        return nodos(raiz).stream()
                .filter(ButtonBase.class::isInstance)
                .map(ButtonBase.class::cast)
                .filter(boton -> boton.getText() != null && boton.getText().trim().endsWith(texto))
                .findFirst()
                .orElseThrow(() -> new AssertionError("No se encontró el botón: " + texto));
    }

    static ToggleButton botonOjo(Node raiz, String textoAccesible) {
        return nodos(raiz).stream()
                .filter(ToggleButton.class::isInstance)
                .map(ToggleButton.class::cast)
                .filter(boton -> textoAccesible.equals(boton.getAccessibleText()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("No se encontró el control de visibilidad: " + textoAccesible));
    }

    static TextField campoTexto(Node raiz, String etiqueta) {
        Node control = controlEtiquetado(raiz, etiqueta);
        return nodos(control).stream()
                .filter(TextField.class::isInstance)
                .map(TextField.class::cast)
                .filter(campo -> !(campo instanceof PasswordField))
                .findFirst()
                .orElseThrow(() -> new AssertionError("No se encontró el campo de texto: " + etiqueta));
    }

    static PasswordField campoContrasena(Node raiz, String etiqueta) {
        Node control = controlEtiquetado(raiz, etiqueta);
        return nodos(control).stream()
                .filter(PasswordField.class::isInstance)
                .map(PasswordField.class::cast)
                .findFirst()
                .orElseThrow(() -> new AssertionError("No se encontró la contraseña: " + etiqueta));
    }

    static ControlConOjo controlConOjo(Node raiz, String etiqueta) {
        return nodos(controlEtiquetado(raiz, etiqueta)).stream()
                .filter(ControlConOjo.class::isInstance)
                .map(ControlConOjo.class::cast)
                .findFirst()
                .orElseThrow(() -> new AssertionError("No se encontró el control con ojo: " + etiqueta));
    }

    static ComboBox<?> combo(Node raiz, String etiqueta) {
        Node control = controlEtiquetado(raiz, etiqueta);
        return nodos(control).stream()
                .filter(ComboBox.class::isInstance)
                .map(ComboBox.class::cast)
                .findFirst()
                .orElseThrow(() -> new AssertionError("No se encontró el selector: " + etiqueta));
    }

    static TextField campoPorPrompt(Node raiz, String prompt) {
        return nodos(raiz).stream()
                .filter(TextField.class::isInstance)
                .map(TextField.class::cast)
                .filter(campo -> prompt.equals(campo.getPromptText()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("No se encontró el campo: " + prompt));
    }

    private static TextField campoDe(SelectorHora selector) {
        return nodos(selector).stream()
                .filter(TextField.class::isInstance)
                .map(TextField.class::cast)
                .findFirst()
                .orElseThrow(() -> new AssertionError("El selector de hora debe incluir su campo editable"));
    }

    private static Node controlEtiquetado(Node raiz, String etiqueta) {
        return nodos(raiz).stream()
                .filter(Label.class::isInstance)
                .map(Label.class::cast)
                .filter(label -> etiqueta.equals(label.getText()))
                .map(Label::getLabelFor)
                .filter(control -> control != null)
                .findFirst()
                .orElseThrow(() -> new AssertionError("No se encontró la etiqueta: " + etiqueta));
    }

    static String textoVisible(Node raiz) {
        return nodos(raiz).stream()
                .filter(Label.class::isInstance)
                .map(Label.class::cast)
                .map(Label::getText)
                .filter(texto -> texto != null && !texto.isBlank())
                .reduce("", (acumulado, texto) -> acumulado + "\n" + texto);
    }

    private static List<Node> nodos(Node raiz) {
        if (raiz == null) {
            return List.of();
        }
        List<Node> resultado = new ArrayList<>();
        resultado.add(raiz);
        if (raiz instanceof Parent padre) {
            padre.getChildrenUnmodifiable().forEach(hijo -> resultado.addAll(nodos(hijo)));
        }
        return resultado;
    }

    static <T> T assertInstanceOf(Object valor, Class<T> tipo) {
        assertTrue(tipo.isInstance(valor), "Se esperaba " + tipo.getSimpleName());
        return tipo.cast(valor);
    }

    static boolean esperar(CheckedBoolean condicion) throws Exception {
        long limite = System.nanoTime() + ESPERA_UI.toNanos();
        while (System.nanoTime() < limite) {
            if (condicion.getAsBoolean()) {
                return true;
            }
            Thread.sleep(40);
        }
        return condicion.getAsBoolean();
    }

    static void fx(Runnable accion) throws Exception {
        fx(() -> {
            accion.run();
            return null;
        });
    }

    static <T> T fx(java.util.concurrent.Callable<T> accion) throws Exception {
        if (Platform.isFxApplicationThread()) {
            return accion.call();
        }
        FutureTask<T> tarea = new FutureTask<>(accion);
        Platform.runLater(tarea);
        try {
            return tarea.get(ESPERA_UI.toSeconds(), TimeUnit.SECONDS);
        } catch (ExecutionException error) {
            if (error.getCause() instanceof Exception excepcion) {
                throw excepcion;
            }
            if (error.getCause() instanceof Error fallo) {
                throw fallo;
            }
            throw error;
        }
    }

    @FunctionalInterface
    interface CheckedBoolean {
        boolean getAsBoolean() throws Exception;
    }
}
