package mx.smartparking.ownerconsole.vista.configuracion;

import java.util.Arrays;
import java.util.Map;
import java.util.Set;
import javafx.scene.Node;
import javafx.scene.layout.VBox;
import mx.smartparking.ownerconsole.modelo.PasoConfiguracion;

/** Presenta contraseña administrativa, confirmación e indicadores de requisitos. */
final class VistaPasoAdministrativa implements VistaPasoAsistente {

    private final ControlConOjo contrasena = new ControlConOjo("Contraseña", "la contraseña de administración");
    private final ControlConOjo confirmacion = new ControlConOjo("Confirmar contraseña", "la confirmación de contraseña");
    private final IndicadorContrasena indicadorLargo = new IndicadorContrasena("Elige una contraseña más larga");
    private final IndicadorContrasena indicadorDiferente = new IndicadorContrasena("Elige una contraseña distinta a la de acceso.");
    private final IndicadorContrasena indicadorCoincidencia = new IndicadorContrasena(
            "Vuelve a escribir la contraseña para comprobar que coincidan.");
    private final CamposPaso campos = new CamposPaso("Contraseña de administración", "");
    private char[] contrasenaAcceso = new char[0];

    VistaPasoAdministrativa() {
        campos.agregarCampoConIndicador(
                "contrasenaAdministrativa",
                "Contraseña",
                contrasena,
                contrasena.oculto(),
                contrasena.visible(),
                null,
                new VBox(3, indicadorLargo, indicadorDiferente));
        campos.agregarCampoConIndicador(
                "confirmacionAdministrativa",
                "Confirmar contraseña",
                confirmacion,
                confirmacion.oculto(),
                confirmacion.visible(),
                null,
                indicadorCoincidencia);
        contrasena.oculto().textProperty().addListener((observable, anterior, actual) -> actualizarIndicadores());
        confirmacion.oculto().textProperty().addListener((observable, anterior, actual) -> actualizarIndicadores());
        actualizarIndicadores();
    }

    @Override
    public PasoConfiguracion paso() {
        return PasoConfiguracion.ADMINISTRACION;
    }

    @Override
    public Node nodo() {
        return campos.contenido();
    }

    @Override
    public void capturar(FormularioAsistente formulario) {
        establecerContrasenaAcceso(formulario.copiarContrasenaAcceso());
        formulario.actualizarAdministracion(
                contrasena.oculto().getText().toCharArray(), confirmacion.oculto().getText().toCharArray());
    }

    @Override
    public void restaurar(FormularioAsistente formulario) {
        establecerContrasenaAcceso(formulario.copiarContrasenaAcceso());
        char[] administrativa = formulario.copiarContrasenaAdministrativa();
        char[] confirmada = formulario.copiarConfirmacionAdministrativa();
        try {
            contrasena.oculto().setText(new String(administrativa));
            confirmacion.oculto().setText(new String(confirmada));
        } finally {
            Arrays.fill(administrativa, '\0');
            Arrays.fill(confirmada, '\0');
        }
        actualizarIndicadores();
    }

    void establecerContrasenaAcceso(char[] valor) {
        Arrays.fill(contrasenaAcceso, '\0');
        contrasenaAcceso = valor == null ? new char[0] : valor.clone();
        if (valor != null) {
            Arrays.fill(valor, '\0');
        }
        actualizarIndicadores();
    }

    @Override
    public void mostrarErrores(Map<String, String> errores) {
        campos.mostrarErrores(errores, Set.of("contrasenaAdministrativa", "confirmacionAdministrativa"));
    }

    @Override
    public void limpiarErrores() {
        campos.limpiarErrores();
    }

    @Override
    public void limpiarContrasenas() {
        contrasena.limpiar();
        confirmacion.limpiar();
        Arrays.fill(contrasenaAcceso, '\0');
        contrasenaAcceso = new char[0];
        actualizarIndicadores();
    }

    private void actualizarIndicadores() {
        char[] administrativa = contrasena.oculto().getText().toCharArray();
        char[] confirmada = confirmacion.oculto().getText().toCharArray();
        try {
            if (Character.codePointCount(administrativa, 0, administrativa.length) >= 10) {
                indicadorLargo.valido("La contraseña es suficientemente larga.");
            } else {
                indicadorLargo.pendiente("Elige una contraseña más larga");
            }

            if (administrativa.length > 0 && contrasenaAcceso.length > 0
                    && !Arrays.equals(administrativa, contrasenaAcceso)) {
                indicadorDiferente.valido("Es diferente a la de acceso");
            } else {
                indicadorDiferente.pendiente("Debe ser diferente a la de acceso");
            }

            if (confirmada.length == 0) {
                indicadorCoincidencia.pendiente("Confirma para comprobar que coincidan");
            } else if (Arrays.equals(administrativa, confirmada)) {
                indicadorCoincidencia.valido("Las contraseñas coinciden");
            } else {
                indicadorCoincidencia.pendiente("Las contraseñas no coinciden");
            }
        } finally {
            Arrays.fill(administrativa, '\0');
            Arrays.fill(confirmada, '\0');
        }
    }
}
