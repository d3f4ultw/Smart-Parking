package mx.smartparking.api.seguridad.cliente;

import jakarta.servlet.http.HttpSession;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Component;

/** Recuerda las sesiones de clientes y permite cerrarlas cuando corresponde. */
@Component
public final class GestorSesionesCliente {

    private static final int MAXIMO_SESIONES = 10_000;

    private final Map<String, RegistroSesion> sesiones = new LinkedHashMap<>(128, 0.75f, true);

    /** Guarda la nueva sesión después de comprobar que el cliente puede entrar. */
    public synchronized void registrar(HttpSession sesion, PrincipalCliente principal) {
        if (sesion == null) {
            throw new IllegalArgumentException("Se requiere una sesión HTTP activa.");
        }
        limpiarSesionesInvalidas();
        while (sesiones.size() >= MAXIMO_SESIONES) {
            revocarLaMasAntigua();
        }
        sesiones.put(sesion.getId(), new RegistroSesion(
                sesion, principal.cuentaId(), principal.revisionAcceso()));
    }

    /** Comprueba que la sesión corresponda al cliente y a la versión actual de su acceso. */
    public synchronized boolean estaRegistrada(String idSesion, PrincipalCliente principal) {
        RegistroSesion registro = sesiones.get(idSesion);
        if (registro == null || !registro.cuentaId().equals(principal.cuentaId())
                || registro.revisionAcceso() != principal.revisionAcceso()) {
            return false;
        }
        if (!estaActiva(registro.sesion())) {
            sesiones.remove(idSesion);
            return false;
        }
        return true;
    }

    /** Retira una sesión sin afectar la sesión administrativa del navegador. */
    public synchronized void olvidar(HttpSession sesion) {
        if (sesion != null) {
            sesiones.remove(sesion.getId());
        }
    }

    /** Cierra las sesiones de la cuenta cuando el cliente cambia su contraseña. */
    public synchronized void revocarCuenta(UUID cuentaId) {
        Iterator<Map.Entry<String, RegistroSesion>> iterador = sesiones.entrySet().iterator();
        while (iterador.hasNext()) {
            RegistroSesion registro = iterador.next().getValue();
            if (registro.cuentaId().equals(cuentaId)) {
                iterador.remove();
                invalidar(registro.sesion());
            }
        }
    }

    private void limpiarSesionesInvalidas() {
        sesiones.entrySet().removeIf(entrada -> !estaActiva(entrada.getValue().sesion()));
    }

    private void revocarLaMasAntigua() {
        Iterator<Map.Entry<String, RegistroSesion>> iterador = sesiones.entrySet().iterator();
        if (iterador.hasNext()) {
            RegistroSesion registro = iterador.next().getValue();
            iterador.remove();
            invalidar(registro.sesion());
        }
    }

    private boolean estaActiva(HttpSession sesion) {
        try {
            sesion.getLastAccessedTime();
            return true;
        } catch (IllegalStateException excepcion) {
            return false;
        }
    }

    private void invalidar(HttpSession sesion) {
        try {
            sesion.invalidate();
        } catch (IllegalStateException excepcion) {
            // Otra solicitud pudo cerrar la sesión al mismo tiempo.
        }
    }

    private record RegistroSesion(HttpSession sesion, UUID cuentaId, long revisionAcceso) {
    }
}
