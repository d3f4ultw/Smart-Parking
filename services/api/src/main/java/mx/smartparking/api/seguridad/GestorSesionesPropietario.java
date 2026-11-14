package mx.smartparking.api.seguridad;

import jakarta.servlet.http.HttpSession;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationEventPublisher;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/** Mantiene registradas las sesiones de propietarios y operadores y permite cerrarlas cuando corresponde. */
@Component
public class GestorSesionesPropietario {

    private static final Logger LOG = LoggerFactory.getLogger(GestorSesionesPropietario.class);
    private static final int MAXIMO_SESIONES_REGISTRADAS = 10_000;

    private final Map<String, RegistroSesion> sesiones = new LinkedHashMap<>(128, 0.75f, true);
    private final ApplicationEventPublisher eventos;

    public GestorSesionesPropietario() {
        this.eventos = null;
    }

    @Autowired
    public GestorSesionesPropietario(ApplicationEventPublisher eventos) {
        this.eventos = eventos;
    }

    /** Registra una sesión del propietario junto con la versión de su acceso. */
    public synchronized void registrar(HttpSession sesion, long revisionPropietario) {
        registrarInterno(sesion, null, 0, revisionPropietario, RolCuenta.DUENO.name());
    }

    /** Registra una sesión del propietario u operador con los datos de su cuenta y su acceso. */
    public synchronized void registrar(HttpSession sesion, PrincipalPropietario principal) {
        registrarInterno(sesion, principal.cuentaId(), principal.revisionAcceso(),
                principal.revisionPropietario(), principal.rol().name());
    }

    private void registrarInterno(
            HttpSession sesion, java.util.UUID cuentaId, long revisionAcceso,
            long revisionPropietario, String rol) {
        if (sesion == null) {
            throw new IllegalArgumentException("Se requiere una sesión HTTP activa.");
        }

        limpiarSesionesInvalidas();
        while (sesiones.size() >= MAXIMO_SESIONES_REGISTRADAS) {
            revocarEntradaMasAntigua();
        }
        sesiones.put(sesion.getId(), new RegistroSesion(
                sesion, cuentaId, revisionAcceso, revisionPropietario, rol));
    }

    /** Cierra las sesiones guardadas con la versión de propietario indicada. */
    public synchronized void revocarRevision(long revisionPropietario) {
        Iterator<Map.Entry<String, RegistroSesion>> iterador = sesiones.entrySet().iterator();
        while (iterador.hasNext()) {
            Map.Entry<String, RegistroSesion> entrada = iterador.next();
            RegistroSesion registro = entrada.getValue();
            if (registro.revisionPropietario() == revisionPropietario) {
                iterador.remove();
                invalidar(entrada.getKey(), registro);
            }
        }
    }

    /** Cierra todas las sesiones que este servicio mantiene registradas. */
    public synchronized void revocarTodas() {
        List<Map.Entry<String, RegistroSesion>> registros = new ArrayList<>(sesiones.entrySet());
        sesiones.clear();
        registros.forEach(entrada -> invalidar(entrada.getKey(), entrada.getValue()));
    }

    /** Retira una sesión concreta, por ejemplo al cerrar sesión voluntariamente. */
    public synchronized void olvidar(HttpSession sesion) {
        if (sesion != null) {
            String idSesion = sesion.getId();
            RegistroSesion registro = sesiones.remove(idSesion);
            if (registro != null) {
                notificarRevocacion(idSesion, registro);
            }
        }
    }

    /** Comprueba que la sesión siga activa y esté registrada con la versión de propietario indicada. */
    public synchronized boolean estaRegistrada(String idSesion, long revisionPropietario) {
        RegistroSesion registro = sesiones.get(idSesion);
        if (registro == null || registro.revisionPropietario() != revisionPropietario) {
            return false;
        }

        if (!estaActiva(registro.sesion())) {
            sesiones.remove(idSesion);
            notificarRevocacion(idSesion, registro);
            return false;
        }
        return true;
    }

    /** Comprueba que la sesión siga activa y pertenezca a la cuenta y el tipo de usuario indicados. */
    public synchronized boolean estaRegistrada(String idSesion, PrincipalPropietario principal) {
        RegistroSesion registro = sesiones.get(idSesion);
        if (registro == null || !principal.cuentaId().equals(registro.cuentaId())
                || principal.revisionAcceso() != registro.revisionAcceso()
                || principal.revisionPropietario() != registro.revisionPropietario()
                || !principal.rol().name().equals(registro.rol())) {
            return false;
        }
        if (!estaActiva(registro.sesion())) {
            sesiones.remove(idSesion);
            notificarRevocacion(idSesion, registro);
            return false;
        }
        return true;
    }

    /**
     * Comprueba que una sesión siga activa utilizando una referencia que no revela su identificador
     * original.
     */
    public synchronized boolean estaRegistradaPorHuella(String huella, java.util.UUID cuentaId,
            long revisionAcceso, long revisionPropietario, String rol) {
        limpiarSesionesInvalidas();
        return sesiones.entrySet().stream().anyMatch(entrada -> {
            RegistroSesion registro = entrada.getValue();
            return cuentaId.equals(registro.cuentaId()) && revisionAcceso == registro.revisionAcceso()
                    && revisionPropietario == registro.revisionPropietario() && rol.equals(registro.rol())
                    && huella.equals(HuellaSesionPropietario.calcular(entrada.getKey()));
        });
    }

    public synchronized void revocarCuenta(java.util.UUID cuentaId) {
        var iterador = sesiones.entrySet().iterator();
        while (iterador.hasNext()) {
            Map.Entry<String, RegistroSesion> entrada = iterador.next();
            RegistroSesion registro = entrada.getValue();
            if (cuentaId.equals(registro.cuentaId())) {
                iterador.remove();
                invalidar(entrada.getKey(), registro);
            }
        }
    }

    /**
     * Entrega referencias de las sesiones del propietario que siguen activas sin revelar sus
     * identificadores originales.
     */
    public synchronized Set<String> huellasSesionesActivas() {
        limpiarSesionesInvalidas();
        return sesiones.entrySet().stream()
                .filter(entrada -> RolCuenta.DUENO.name().equals(entrada.getValue().rol()))
                .map(entrada -> HuellaSesionPropietario.calcular(entrada.getKey()))
                .collect(Collectors.toUnmodifiableSet());
    }

    private void limpiarSesionesInvalidas() {
        Iterator<Map.Entry<String, RegistroSesion>> iterador = sesiones.entrySet().iterator();
        while (iterador.hasNext()) {
            Map.Entry<String, RegistroSesion> entrada = iterador.next();
            if (!estaActiva(entrada.getValue().sesion())) {
                notificarRevocacion(entrada.getKey(), entrada.getValue());
                iterador.remove();
            }
        }
    }

    private void revocarEntradaMasAntigua() {
        Iterator<Map.Entry<String, RegistroSesion>> iterador = sesiones.entrySet().iterator();
        if (iterador.hasNext()) {
            Map.Entry<String, RegistroSesion> entrada = iterador.next();
            iterador.remove();
            invalidar(entrada.getKey(), entrada.getValue());
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

    private void invalidar(String idSesion, RegistroSesion registro) {
        notificarRevocacion(idSesion, registro);
        try {
            registro.sesion().invalidate();
        } catch (IllegalStateException excepcion) {
            // La sesión ya terminó o fue cerrada por otra solicitud.
        }
    }

    private void notificarRevocacion(String idSesion, RegistroSesion registro) {
        if (eventos != null && RolCuenta.DUENO.name().equals(registro.rol())) {
            try {
                eventos.publishEvent(new SesionPropietarioRevocada(HuellaSesionPropietario.calcular(idSesion)));
            } catch (RuntimeException excepcion) {
                LOG.warn("No se pudo limpiar la captura RFID al revocar la sesión del propietario.");
            }
        }
    }

    private record RegistroSesion(
            HttpSession sesion,
            java.util.UUID cuentaId,
            long revisionAcceso,
            long revisionPropietario,
            String rol) {
    }
}
