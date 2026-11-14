package mx.smartparking.ownerconsole.vista.configuracion;

import java.util.Map;
import javafx.scene.Node;
import javafx.scene.control.ComboBox;
import javafx.util.StringConverter;
import mx.smartparking.ownerconsole.modelo.PasoConfiguracion;

/** Presenta nombre y tipo del estacionamiento. */
final class VistaPasoEstacionamiento implements VistaPasoAsistente {

    private final javafx.scene.control.TextField nombre = new javafx.scene.control.TextField();
    private final ComboBox<TipoOpcion> tipo = new ComboBox<>();
    private final CamposPaso campos = new CamposPaso(
            "Datos del estacionamiento", "Podrás cambiar el nombre y el tipo más adelante.");

    VistaPasoEstacionamiento() {
        tipo.setPromptText("Selecciona una opción");
        tipo.getItems().setAll(TipoOpcion.values());
        tipo.setConverter(new StringConverter<>() {
            @Override
            public String toString(TipoOpcion opcion) {
                return opcion == null ? "" : opcion.etiqueta();
            }

            @Override
            public TipoOpcion fromString(String texto) {
                return null;
            }
        });
        campos.agregarCampo("nombreEstacionamiento", "Nombre del estacionamiento", nombre, null);
        campos.agregarCampo("tipoEstacionamiento", "Tipo de estacionamiento", tipo, null);
    }

    @Override
    public PasoConfiguracion paso() {
        return PasoConfiguracion.ESTACIONAMIENTO;
    }

    @Override
    public Node nodo() {
        return campos.contenido();
    }

    @Override
    public void capturar(FormularioAsistente formulario) {
        formulario.actualizarEstacionamiento(
                nombre.getText().trim(), tipo.getValue() == null ? "" : tipo.getValue().codigo());
    }

    @Override
    public void restaurar(FormularioAsistente formulario) {
        nombre.setText(formulario.nombreEstacionamiento());
        tipo.getItems().stream()
                .filter(opcion -> opcion.codigo().equals(formulario.tipoEstacionamiento()))
                .findFirst()
                .ifPresentOrElse(tipo::setValue, () -> tipo.setValue(null));
    }

    @Override
    public void mostrarErrores(Map<String, String> errores) {
        campos.mostrarErrores(errores);
    }

    @Override
    public void limpiarErrores() {
        campos.limpiarErrores();
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

        String etiqueta() {
            return etiqueta;
        }
    }
}
