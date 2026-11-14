package mx.smartparking.ownerconsole.vista.configuracion;

import java.util.Map;
import javafx.geometry.Insets;
import javafx.scene.Node;
import javafx.scene.control.RadioButton;
import javafx.scene.control.TextField;
import javafx.scene.control.ToggleGroup;
import javafx.scene.layout.VBox;
import mx.smartparking.ownerconsole.modelo.PasoConfiguracion;
import mx.smartparking.ownerconsole.vista.SelectorHora;

/** Presenta el modo de operación, la zona horaria y el intervalo diario. */
final class VistaPasoHorario implements VistaPasoAsistente {

    private final RadioButton continuo = new RadioButton("Abierto las 24 horas");
    private final RadioButton intervalo = new RadioButton("Horario fijo todos los días");
    private final SelectorZonaHoraria zonaHoraria = new SelectorZonaHoraria();
    private final TextField horaApertura = new TextField("09:00");
    private final TextField horaCierre = new TextField("18:00");
    private final SelectorHora selectorApertura = new SelectorHora(horaApertura, "Apertura");
    private final SelectorHora selectorCierre = new SelectorHora(horaCierre, "Cierre");
    private final CamposPaso campos = new CamposPaso(
            "Horario del estacionamiento", "Puedes establecer horarios que terminen después de medianoche.");

    VistaPasoHorario() {
        ToggleGroup grupo = new ToggleGroup();
        continuo.setToggleGroup(grupo);
        intervalo.setToggleGroup(grupo);
        VBox opciones = new VBox(4, continuo, intervalo);
        opciones.setPadding(new Insets(4, 8, 4, 8));
        campos.agregarGrupoOpciones("modoHorario", "Horario de atención", opciones, continuo);
        campos.agregarCampo("zonaHoraria", "Zona horaria", zonaHoraria, null);
        campos.agregarCampoConIndicador(
                "horaApertura", "Apertura", selectorApertura, horaApertura, null, null, null);
        campos.agregarCampoConIndicador(
                "horaCierre", "Cierre", selectorCierre, horaCierre, null, null, null);
        selectorApertura.disableProperty().bind(intervalo.selectedProperty().not());
        selectorCierre.disableProperty().bind(intervalo.selectedProperty().not());
        continuo.selectedProperty().addListener((observable, anterior, seleccionado) -> {
            if (seleccionado) {
                campos.limpiarError("modoHorario");
            }
        });
        intervalo.selectedProperty().addListener((observable, anterior, seleccionado) -> {
            if (seleccionado) {
                campos.limpiarError("modoHorario");
            }
        });
    }

    @Override
    public PasoConfiguracion paso() {
        return PasoConfiguracion.HORARIO;
    }

    @Override
    public Node nodo() {
        return campos.contenido();
    }

    @Override
    public void capturar(FormularioAsistente formulario) {
        String modo = continuo.isSelected()
                ? "CONTINUO_24_7"
                : intervalo.isSelected() ? "INTERVALO_DIARIO" : "";
        formulario.actualizarHorario(
                modo,
                zonaHoraria.getText().trim(),
                horaApertura.getText().trim(),
                horaCierre.getText().trim());
    }

    @Override
    public void restaurar(FormularioAsistente formulario) {
        continuo.setSelected("CONTINUO_24_7".equals(formulario.modoHorario()));
        intervalo.setSelected("INTERVALO_DIARIO".equals(formulario.modoHorario()));
        zonaHoraria.setText(formulario.zonaHoraria());
        horaApertura.setText(formulario.horaApertura());
        horaCierre.setText(formulario.horaCierre());
    }

    @Override
    public void mostrarErrores(Map<String, String> errores) {
        campos.mostrarErrores(errores);
    }

    @Override
    public void limpiarErrores() {
        campos.limpiarErrores();
    }

    void ocultarSugerencias() {
        zonaHoraria.ocultarSugerencias();
    }
}
