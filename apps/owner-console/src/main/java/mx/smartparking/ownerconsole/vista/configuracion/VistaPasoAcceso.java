package mx.smartparking.ownerconsole.vista.configuracion;

import java.util.Map;
import java.util.Set;
import javafx.scene.Node;
import mx.smartparking.ownerconsole.modelo.PasoConfiguracion;

/** Presenta el correo y la contraseña regular del propietario. */
final class VistaPasoAcceso implements VistaPasoAsistente {

    private final javafx.scene.control.TextField correo = new javafx.scene.control.TextField();
    private final ControlConOjo contrasena = new ControlConOjo("Contraseña", "la contraseña de acceso");
    private final IndicadorContrasena indicadorLargo = new IndicadorContrasena("Elige una contraseña más larga");
    private final CamposPaso campos = new CamposPaso("Acceso del propietario", "");

    VistaPasoAcceso() {
        campos.agregarCampo("correo", "Correo electrónico", correo, null);
        campos.agregarCampoConIndicador(
                "contrasenaAcceso",
                "Contraseña",
                contrasena,
                contrasena.oculto(),
                contrasena.visible(),
                null,
                indicadorLargo);
        contrasena.oculto().textProperty().addListener(
                (observable, anterior, actual) -> actualizarIndicadorLargo(actual));
        actualizarIndicadorLargo("");
    }

    @Override
    public PasoConfiguracion paso() {
        return PasoConfiguracion.ACCESO;
    }

    @Override
    public Node nodo() {
        return campos.contenido();
    }

    @Override
    public void capturar(FormularioAsistente formulario) {
        formulario.actualizarAcceso(correo.getText().trim(), contrasena.oculto().getText().toCharArray());
    }

    @Override
    public void restaurar(FormularioAsistente formulario) {
        correo.setText(formulario.correo());
        char[] secreto = formulario.copiarContrasenaAcceso();
        try {
            contrasena.oculto().setText(new String(secreto));
        } finally {
            java.util.Arrays.fill(secreto, '\0');
        }
        actualizarIndicadorLargo(contrasena.oculto().getText());
    }

    @Override
    public void mostrarErrores(Map<String, String> errores) {
        campos.mostrarErrores(errores, Set.of("contrasenaAcceso"));
    }

    @Override
    public void limpiarErrores() {
        campos.limpiarErrores();
    }

    @Override
    public void limpiarContrasenas() {
        contrasena.limpiar();
        actualizarIndicadorLargo("");
    }

    char[] copiarContrasenaActual() {
        return contrasena.oculto().getText().toCharArray();
    }

    private void actualizarIndicadorLargo(String secreto) {
        int largo = secreto == null ? 0 : secreto.codePointCount(0, secreto.length());
        if (largo >= 10) {
            indicadorLargo.valido("La contraseña es suficientemente larga.");
        } else {
            indicadorLargo.pendiente("Elige una contraseña más larga");
        }
    }
}
