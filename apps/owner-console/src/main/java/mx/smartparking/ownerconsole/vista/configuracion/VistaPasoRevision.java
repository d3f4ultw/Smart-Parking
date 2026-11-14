package mx.smartparking.ownerconsole.vista.configuracion;

import java.util.Map;
import javafx.geometry.Insets;
import javafx.scene.Node;
import javafx.scene.control.Label;
import javafx.scene.layout.VBox;
import mx.smartparking.ownerconsole.modelo.PasoConfiguracion;

/** Presenta el resumen de propietario, estacionamiento y horario antes de confirmar. */
final class VistaPasoRevision implements VistaPasoAsistente {

    private final Label resumenIdentidad = new Label();
    private final Label resumenAcceso = new Label();
    private final Label resumenEstacionamiento = new Label();
    private final Label resumenHorario = new Label();
    private final CamposPaso campos = new CamposPaso("Revisa y confirma", "");

    VistaPasoRevision() {
        Label ayuda = new Label("Comprueba que la información sea correcta antes de guardar.");
        ayuda.setWrapText(true);
        ayuda.getStyleClass().add("texto-ayuda");
        VBox resumen = new VBox(
                14,
                crearDatoResumen("Propietario", resumenIdentidad),
                crearDatoResumen("Correo electrónico", resumenAcceso),
                crearDatoResumen("Estacionamiento", resumenEstacionamiento),
                crearDatoResumen("Horario de atención", resumenHorario));
        resumen.getStyleClass().add("panel-resumen");
        resumen.setPadding(new Insets(12, 14, 12, 14));
        campos.agregarContenido(ayuda);
        campos.agregarContenido(resumen);
    }

    @Override
    public PasoConfiguracion paso() {
        return PasoConfiguracion.REVISION;
    }

    @Override
    public Node nodo() {
        return campos.contenido();
    }

    @Override
    public void capturar(FormularioAsistente formulario) {
        // El resumen no agrega campos al formulario.
    }

    @Override
    public void restaurar(FormularioAsistente formulario) {
        actualizarRevision(formulario);
    }

    @Override
    public void actualizarRevision(FormularioAsistente formulario) {
        resumenIdentidad.setText(String.join(
                " ",
                formulario.nombres(),
                formulario.primerApellido(),
                formulario.segundoApellido())
                .trim().replaceAll("\\s+", " "));
        resumenAcceso.setText(formulario.correo());
        resumenEstacionamiento.setText(
                formulario.nombreEstacionamiento() + " · " + etiquetaTipo(formulario.tipoEstacionamiento()));
        if ("CONTINUO_24_7".equals(formulario.modoHorario())) {
            resumenHorario.setText("Abierto todo el día · " + formulario.zonaHoraria());
        } else {
            resumenHorario.setText(formulario.horaApertura() + "–" + formulario.horaCierre()
                    + " · " + formulario.zonaHoraria());
        }
    }

    @Override
    public void mostrarErrores(Map<String, String> errores) {
        campos.mostrarErrores(errores);
    }

    @Override
    public void limpiarErrores() {
        campos.limpiarErrores();
    }

    private VBox crearDatoResumen(String etiqueta, Label valor) {
        Label nombre = new Label(etiqueta);
        nombre.getStyleClass().add("text-muted");
        valor.getStyleClass().add("text-bold");
        valor.setWrapText(true);
        return new VBox(6, nombre, valor);
    }

    private String etiquetaTipo(String tipo) {
        return switch (tipo == null ? "" : tipo) {
            case "PUBLICO" -> "Público";
            case "PRIVADO" -> "Privado";
            case "MIXTO" -> "Mixto";
            default -> tipo == null ? "" : tipo;
        };
    }
}
