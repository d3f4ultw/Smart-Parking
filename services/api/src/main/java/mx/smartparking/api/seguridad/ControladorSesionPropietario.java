package mx.smartparking.api.seguridad;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpSession;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Locale;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.AuthenticationServiceException;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.context.SecurityContextRepository;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.security.web.csrf.CsrfTokenRepository;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Permite al propietario y al operador entrar, consultar su acceso y cerrar sesión de forma protegida. */
@RestController
@RequestMapping("/api/v1")
public class ControladorSesionPropietario {

    private static final String ERROR_CREDENCIALES = "Correo o contraseña no válidos.";
    private static final String ERROR_API = "No pudimos comprobar tu acceso en este momento. Inténtalo más tarde.";
    private static final String CODIGO_CREDENCIALES = "CREDENCIALES_NO_VALIDAS";
    private static final int MAXIMO_CORREO = 254;

    private final AuthenticationManager administradorAutenticacion;
    private final SecurityContextRepository repositorioContexto;
    private final CsrfTokenRepository repositorioCsrf;
    private final GestorSesionesPropietario gestorSesiones;
    private final ProteccionIntentosInicioSesion proteccionIntentos;
    private final RepositorioCuentas cuentas;

    /** Prepara los componentes necesarios para comprobar el acceso y administrar las sesiones. */
    public ControladorSesionPropietario(
            AuthenticationManager administradorAutenticacion,
            SecurityContextRepository repositorioContexto,
            CsrfTokenRepository repositorioCsrf,
            GestorSesionesPropietario gestorSesiones,
            ProteccionIntentosInicioSesion proteccionIntentos,
            RepositorioCuentas cuentas) {
        this.administradorAutenticacion = administradorAutenticacion;
        this.repositorioContexto = repositorioContexto;
        this.repositorioCsrf = repositorioCsrf;
        this.gestorSesiones = gestorSesiones;
        this.proteccionIntentos = proteccionIntentos;
        this.cuentas = cuentas;
    }

    /**
     * Entrega un código que ayuda a comprobar que las solicitudes de cambio provienen de la sesión
     * legítima.
     */
    @GetMapping("/csrf")
    public RespuestaCsrf obtenerTokenCsrf(HttpServletRequest solicitud, HttpServletResponse respuesta) {
        CsrfToken token = repositorioCsrf.loadToken(solicitud);
        if (token == null) {
            token = repositorioCsrf.generateToken(solicitud);
            repositorioCsrf.saveToken(token, solicitud, respuesta);
        }
        return new RespuestaCsrf(token.getToken());
    }

    /** Indica si la sesión pertenece a un propietario u operador que ya inició sesión. */
    @GetMapping("/sesion")
    public RespuestaSesion consultarSesion() {
        Authentication autenticacion = SecurityContextHolder.getContext().getAuthentication();
        if (autenticacion != null
                && autenticacion.isAuthenticated()
                && autenticacion.getPrincipal() instanceof PrincipalPropietario principal) {
            return new RespuestaSesion(true, principal.correo(), principal.revisionPropietario(), null,
                    principal.rol().name());
        }
        return new RespuestaSesion(false, null, null, null, null);
    }

    /** Comprueba el correo y la contraseña de una cuenta de propietario u operador autorizada. */
    @PostMapping("/sesion")
    public ResponseEntity<?> iniciarSesion(
            @RequestBody(required = false) SolicitudInicioSesion cuerpo,
            HttpServletRequest solicitud,
            HttpServletResponse respuesta) {
        if (cuerpo == null) {
            return ResponseEntity.badRequest().body(new RespuestaError(
                    "SOLICITUD_NO_VALIDA", "Revisa tu correo y contraseña e inténtalo de nuevo."));
        }

        String correo = normalizarCorreo(cuerpo.correo());
        String claveIntentos = crearClaveIntentos(correo);
        if (proteccionIntentos.estaBloqueado(claveIntentos)) {
            return noAutenticado();
        }

        if (correo.length() > MAXIMO_CORREO || cuerpo.contrasena() == null) {
            proteccionIntentos.registrarFallo(claveIntentos);
            return noAutenticado();
        }

        Authentication autenticacion;
        try {
            autenticacion = administradorAutenticacion.authenticate(
                    UsernamePasswordAuthenticationToken.unauthenticated(correo, cuerpo.contrasena()));
        } catch (DataAccessException excepcion) {
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                    .body(new RespuestaError("API_NO_DISPONIBLE", ERROR_API));
        } catch (AuthenticationServiceException excepcion) {
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                    .body(new RespuestaError("API_NO_DISPONIBLE", ERROR_API));
        } catch (AuthenticationException excepcion) {
            proteccionIntentos.registrarFallo(claveIntentos);
            return noAutenticado();
        }

        if (!(autenticacion.getPrincipal() instanceof PrincipalPropietario principal)) {
            proteccionIntentos.registrarFallo(claveIntentos);
            return noAutenticado();
        }

        if (principal.rol() == RolCuenta.OPERADOR) {
            try {
                if (!cuentas.sesionVigente(principal.cuentaId(), principal.revisionAcceso(),
                        principal.rol().name(), principal.revisionPropietario())) {
                    proteccionIntentos.registrarFallo(claveIntentos);
                    return noAutenticado();
                }
            } catch (DataAccessException excepcion) {
                return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                        .body(new RespuestaError("API_NO_DISPONIBLE", ERROR_API));
            }
        }

        HttpSession sesionAnterior = solicitud.getSession(false);
        if (sesionAnterior == null) {
            solicitud.getSession(true);
        } else {
            gestorSesiones.olvidar(sesionAnterior);
        }
        solicitud.changeSessionId();

        SecurityContext contexto = SecurityContextHolder.createEmptyContext();
        contexto.setAuthentication(autenticacion);
        SecurityContextHolder.setContext(contexto);
        repositorioContexto.saveContext(contexto, solicitud, respuesta);

        HttpSession sesionActual = solicitud.getSession(false);
        gestorSesiones.registrar(sesionActual, principal);
        proteccionIntentos.registrarExito(claveIntentos);
        String tokenCsrf = renovarTokenCsrf(solicitud, respuesta);

        RespuestaSesion resultado = new RespuestaSesion(
                true,
                principal.correo(),
                principal.revisionPropietario(),
                tokenCsrf,
                principal.rol().name());
        return ResponseEntity.ok(resultado);
    }

    /** Cierra la sesión actual y prepara un nuevo código de protección para quien aún no ha iniciado sesión. */
    @DeleteMapping("/sesion")
    public RespuestaSesion cerrarSesion(HttpServletRequest solicitud, HttpServletResponse respuesta) {
        HttpSession sesion = solicitud.getSession(false);
        if (sesion != null) {
            gestorSesiones.olvidar(sesion);
        }
        SecurityContextHolder.clearContext();
        if (sesion != null) {
            try {
                sesion.invalidate();
            } catch (IllegalStateException excepcion) {
                // Otra solicitud pudo cerrar la sesión al mismo tiempo.
            }
        }

        String tokenCsrf = renovarTokenCsrf(solicitud, respuesta);
        return new RespuestaSesion(false, null, null, tokenCsrf, null);
    }

    private ResponseEntity<RespuestaError> noAutenticado() {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(new RespuestaError(CODIGO_CREDENCIALES, ERROR_CREDENCIALES));
    }

    private String renovarTokenCsrf(HttpServletRequest solicitud, HttpServletResponse respuesta) {
        repositorioCsrf.saveToken(null, solicitud, respuesta);
        CsrfToken token = repositorioCsrf.generateToken(solicitud);
        repositorioCsrf.saveToken(token, solicitud, respuesta);
        return token.getToken();
    }

    private String normalizarCorreo(String correo) {
        return correo == null ? "" : correo.trim().toLowerCase(Locale.ROOT);
    }

    private String crearClaveIntentos(String correoNormalizado) {
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256")
                    .digest(correoNormalizado.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(hash);
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException("No pudimos completar la acción en este momento.", excepcion);
        }
    }

    /** Reúne el correo y la contraseña para entrar sin mostrarlos si los datos se convierten en texto. */
    private record SolicitudInicioSesion(String correo, String contrasena) {
        @Override
        public String toString() {
            return "SolicitudInicioSesion[redactada]";
        }
    }

    private record RespuestaCsrf(String token) {
    }

    private record RespuestaSesion(
            boolean autenticada,
            String correo,
            Long revisionPropietario,
            String csrfToken,
            String rol) {
    }

    private record RespuestaError(String codigo, String error) {
    }
}
