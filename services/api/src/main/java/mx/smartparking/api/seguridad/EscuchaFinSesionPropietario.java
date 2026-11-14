package mx.smartparking.api.seguridad;

import jakarta.servlet.http.HttpSessionEvent;
import jakarta.servlet.http.HttpSessionListener;
import org.springframework.stereotype.Component;

/** Olvida la referencia de la sesión del propietario cuando vence o se cierra. */
@Component
public final class EscuchaFinSesionPropietario implements HttpSessionListener {

    private final GestorSesionesPropietario gestor;

    public EscuchaFinSesionPropietario(GestorSesionesPropietario gestor) {
        this.gestor = gestor;
    }

    @Override
    public void sessionDestroyed(HttpSessionEvent evento) {
        gestor.olvidar(evento.getSession());
    }
}
