package mx.smartparking.api.seguridad.cliente;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpSession;
import java.io.IOException;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.dao.DataAccessException;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/** Comprueba en cada solicitud que la sesión del cliente y su acceso sigan vigentes. */
public final class FiltroSesionCliente extends OncePerRequestFilter {

    private static final String ERROR_SESION =
            "{\"codigo\":\"SESION_NO_VIGENTE\",\"error\":\"La sesión no está vigente.\"}";

    private final GestorSesionesCliente sesiones;
    private final RepositorioCuentas cuentas;

    public FiltroSesionCliente(GestorSesionesCliente sesiones, RepositorioCuentas cuentas) {
        this.sesiones = sesiones;
        this.cuentas = cuentas;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest solicitud,
            HttpServletResponse respuesta,
            FilterChain cadena) throws ServletException, IOException {
        Authentication autenticacion = SecurityContextHolder.getContext().getAuthentication();
        if (autenticacion == null || !autenticacion.isAuthenticated()
                || !(autenticacion.getPrincipal() instanceof PrincipalCliente principal)) {
            cadena.doFilter(solicitud, respuesta);
            return;
        }

        HttpSession sesion = solicitud.getSession(false);
        boolean vigente = sesion != null && sesiones.estaRegistrada(sesion.getId(), principal);
        if (vigente) {
            try {
                vigente = cuentas.sesionVigente(
                        principal.cuentaId(), principal.revisionAcceso(), RolCuenta.CLIENTE.name(), 0L);
            } catch (DataAccessException excepcion) {
                escribirError(respuesta, HttpServletResponse.SC_SERVICE_UNAVAILABLE,
                        "API_NO_DISPONIBLE", "No pudimos comprobar tu acceso. Inténtalo más tarde.");
                return;
            }
        }
        if (vigente) {
            cadena.doFilter(solicitud, respuesta);
            return;
        }

        SecurityContextHolder.clearContext();
        if (sesion != null) {
            sesiones.olvidar(sesion);
            try {
                sesion.invalidate();
            } catch (IllegalStateException excepcion) {
                // Otra solicitud pudo cerrar la sesión al mismo tiempo.
            }
        }
        expirarCookieCliente(solicitud, respuesta);
        respuesta.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        respuesta.setContentType("application/json");
        respuesta.setCharacterEncoding("UTF-8");
        respuesta.setHeader("Cache-Control", "no-store, private");
        respuesta.setHeader("Vary", "Cookie");
        respuesta.getWriter().write(ERROR_SESION);
    }

    private static void expirarCookieCliente(HttpServletRequest solicitud, HttpServletResponse respuesta) {
        String cookie = "JSESSIONID=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict";
        respuesta.addHeader("Set-Cookie", cookie + (solicitud.isSecure() ? "; Secure" : ""));
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
