package mx.smartparking.api.seguridad;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpSession;
import java.io.IOException;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import org.springframework.dao.DataAccessException;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/** Comprueba en cada solicitud que la cuenta y la sesión todavía tengan permiso para continuar. */
public class FiltroSesionPropietario extends OncePerRequestFilter {

    private static final String ERROR_SESION_INVALIDA =
            "{\"codigo\":\"SESION_NO_VIGENTE\",\"error\":\"La sesión no está vigente.\"}";

    private final GestorSesionesPropietario gestorSesiones;
    private final RepositorioCuentas cuentas;

    public FiltroSesionPropietario(GestorSesionesPropietario gestorSesiones) {
        this(gestorSesiones, null);
    }

    public FiltroSesionPropietario(
            GestorSesionesPropietario gestorSesiones, RepositorioCuentas cuentas) {
        this.gestorSesiones = gestorSesiones;
        this.cuentas = cuentas;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest solicitud,
            HttpServletResponse respuesta,
            FilterChain cadena) throws ServletException, IOException {
        Authentication autenticacion = SecurityContextHolder.getContext().getAuthentication();
        if (autenticacion == null || !autenticacion.isAuthenticated()
                || !(autenticacion.getPrincipal() instanceof PrincipalPropietario principal)) {
            cadena.doFilter(solicitud, respuesta);
            return;
        }

        HttpSession sesion = solicitud.getSession(false);
        boolean vigente = sesion != null && gestorSesiones.estaRegistrada(sesion.getId(), principal);
        if (vigente && cuentas != null) {
            try {
                vigente = cuentas.sesionVigente(principal.cuentaId(), principal.revisionAcceso(),
                        principal.rol().name(), principal.revisionPropietario());
            } catch (DataAccessException excepcion) {
                escribirError(respuesta, HttpServletResponse.SC_SERVICE_UNAVAILABLE,
                        "API_NO_DISPONIBLE", "No pudimos comprobar tu acceso en este momento. Inténtalo más tarde.");
                return;
            }
        }
        if (vigente) {
            cadena.doFilter(solicitud, respuesta);
            return;
        }

        SecurityContextHolder.clearContext();
        if (sesion != null) {
            gestorSesiones.olvidar(sesion);
            try {
                sesion.invalidate();
            } catch (IllegalStateException excepcion) {
                // Otra solicitud pudo cerrar la sesión al mismo tiempo.
            }
        }
        respuesta.addHeader("Set-Cookie", "JSESSIONID=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"
                + (solicitud.isSecure() ? "; Secure" : ""));
        respuesta.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        respuesta.setContentType("application/json");
        respuesta.setCharacterEncoding("UTF-8");
                respuesta.setHeader("Cache-Control", "no-store, private");
                respuesta.setHeader("Vary", "Cookie");
        respuesta.getWriter().write(ERROR_SESION_INVALIDA);
    }

    private static void escribirError(
            HttpServletResponse respuesta, int estado, String codigo, String mensaje) throws IOException {
        respuesta.setStatus(estado);
        respuesta.setContentType("application/json");
        respuesta.setCharacterEncoding("UTF-8");
        respuesta.setHeader("Cache-Control", "no-store, private");
        respuesta.setHeader("Vary", "Cookie");
        respuesta.getWriter().write("{\"codigo\":\"" + codigo + "\",\"error\":\"" + mensaje + "\"}");
    }
}
