package mx.smartparking.ownerconsole.vista.configuracion;

import java.util.Map;
import javafx.scene.Node;
import mx.smartparking.ownerconsole.modelo.PasoConfiguracion;

interface VistaPasoAsistente {

    PasoConfiguracion paso();

    Node nodo();

    void capturar(FormularioAsistente formulario);

    void restaurar(FormularioAsistente formulario);

    void mostrarErrores(Map<String, String> errores);

    void limpiarErrores();

    default void actualizarRevision(FormularioAsistente formulario) {
    }

    default void limpiarContrasenas() {
    }
}
