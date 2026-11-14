package mx.smartparking.ownerconsole.vista.configuracion;

import java.util.Map;
import javafx.scene.Node;
import javafx.scene.control.TextField;
import mx.smartparking.ownerconsole.modelo.PasoConfiguracion;

/** Presenta y captura los datos de identidad del propietario. */
final class VistaPasoIdentidad implements VistaPasoAsistente {

    private final TextField nombres = new TextField();
    private final TextField primerApellido = new TextField();
    private final TextField segundoApellido = new TextField();
    private final CamposPaso campos = new CamposPaso("Datos del propietario", "");

    VistaPasoIdentidad() {
        campos.agregarCampo("nombres", "Nombres", nombres, null);
        campos.agregarCampo("primerApellido", "Primer apellido", primerApellido, null);
        campos.agregarCampo("segundoApellido", "Segundo apellido (opcional)", segundoApellido, null);
    }

    @Override
    public PasoConfiguracion paso() {
        return PasoConfiguracion.IDENTIDAD;
    }

    @Override
    public Node nodo() {
        return campos.contenido();
    }

    @Override
    public void capturar(FormularioAsistente formulario) {
        formulario.actualizarIdentidad(
                nombres.getText().trim(), primerApellido.getText().trim(), segundoApellido.getText().trim());
    }

    @Override
    public void restaurar(FormularioAsistente formulario) {
        nombres.setText(formulario.nombres());
        primerApellido.setText(formulario.primerApellido());
        segundoApellido.setText(formulario.segundoApellido());
    }

    @Override
    public void mostrarErrores(Map<String, String> errores) {
        campos.mostrarErrores(errores);
    }

    @Override
    public void limpiarErrores() {
        campos.limpiarErrores();
    }
}
