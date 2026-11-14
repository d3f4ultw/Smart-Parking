package mx.smartparking.api.clientes.controlador;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpSession;
import java.util.UUID;
import mx.smartparking.api.clientes.modelo.PortalCliente;
import mx.smartparking.api.clientes.servicio.ServicioClientes;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.seguridad.cliente.GestorSesionesCliente;
import mx.smartparking.api.seguridad.cliente.PrincipalCliente;
import mx.smartparking.api.seguridad.cliente.ProteccionIntentosInicioSesionCliente;
import mx.smartparking.api.seguridad.cliente.ProteccionIntentosRegistroCliente;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.dao.DataAccessException;
import org.springframework.transaction.TransactionException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.AuthenticationServiceException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.context.SecurityContextRepository;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.security.web.csrf.CsrfTokenRepository;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.http.converter.HttpMessageNotReadableException;

/** Permite al cliente crear su cuenta, entrar, salir y consultar su información personal. */
@RestController
@RequestMapping("/api/v1/clientes")
public final class ControladorClientes {

    private static final String ERROR_CREDENCIALES = "Correo o contraseña no válidos.";
    private static final String ERROR_SERVICIO = "No pudimos completar esto ahora. Inténtalo más tarde.";
    private static final String ERROR_REGISTRO = "No pudimos completar el registro con esos datos.";
    private static final String ERROR_VALIDACION = "Revisa tus datos e inténtalo de nuevo.";

    private final AuthenticationManager administradorAutenticacion;
    private final SecurityContextRepository repositorioContexto;
    private final CsrfTokenRepository repositorioCsrf;
    private final GestorSesionesCliente gestorSesiones;
    private final ProteccionIntentosInicioSesionCliente proteccionInicioSesion;
    private final ProteccionIntentosRegistroCliente proteccionRegistro;
    private final ServicioClientes servicioClientes;

    public ControladorClientes(
            @Qualifier("clienteAuthenticationManager") AuthenticationManager administradorAutenticacion,
            SecurityContextRepository repositorioContexto,
            CsrfTokenRepository repositorioCsrf,
            GestorSesionesCliente gestorSesiones,
            ProteccionIntentosInicioSesionCliente proteccionInicioSesion,
            ProteccionIntentosRegistroCliente proteccionRegistro,
            ServicioClientes servicioClientes) {
        this.administradorAutenticacion = administradorAutenticacion;
        this.repositorioContexto = repositorioContexto;
        this.repositorioCsrf = repositorioCsrf;
        this.gestorSesiones = gestorSesiones;
        this.proteccionInicioSesion = proteccionInicioSesion;
        this.proteccionRegistro = proteccionRegistro;
        this.servicioClientes = servicioClientes;
    }

    /** Entrega un código de seguridad que protege las acciones de la cuenta del cliente. */
    @GetMapping("/csrf")
    public ResponseEntity<RespuestaCsrf> obtenerTokenCsrf(
            HttpServletRequest solicitud, HttpServletResponse respuesta) {
        CsrfToken token = repositorioCsrf.loadToken(solicitud);
        if (token == null) {
            token = repositorioCsrf.generateToken(solicitud);
            repositorioCsrf.saveToken(token, solicitud, respuesta);
        }
        return ResponseEntity.ok().headers(encabezadosPrivados()).body(new RespuestaCsrf(token.getToken()));
    }

    /** Crea la cuenta del cliente; para entrar debe iniciar sesión y la membresía se contrata por separado. */
    @PostMapping("/registro")
    public ResponseEntity<?> registrarCliente(@RequestBody(required = false) SolicitudRegistro cuerpo) {
        if (cuerpo == null) {
            return error(HttpStatus.BAD_REQUEST, "VALIDACION", ERROR_VALIDACION);
        }

        String correo = normalizarCorreo(cuerpo.correo());
        if (!proteccionRegistro.admitirSolicitud(ValidadorClientes.crearClaveHash(correo))) {
            return error(HttpStatus.TOO_MANY_REQUESTS, "INTENTOS_LIMITADOS", ERROR_VALIDACION);
        }
        SolicitudRegistro validada = validarRegistro(cuerpo, correo);
        if (validada == null) {
            return error(HttpStatus.BAD_REQUEST, "VALIDACION", ERROR_VALIDACION);
        }

        try {
            UUID clienteId = servicioClientes.registrarCliente(
                    validada.nombres(), validada.primerApellido(), validada.segundoApellido(),
                    correo, validada.contrasena());
            return ResponseEntity.status(HttpStatus.CREATED)
                    .headers(encabezadosPrivados())
                    .body(new RespuestaRegistro(clienteId, correo));
        } catch (ErrorConfiguracion excepcion) {
            if (excepcion.estadoHttp() == HttpStatus.CONFLICT) {
                return error(HttpStatus.CONFLICT, "REGISTRO_NO_DISPONIBLE", ERROR_REGISTRO);
            }
            if (excepcion.estadoHttp() == HttpStatus.TOO_MANY_REQUESTS) {
                return error(HttpStatus.TOO_MANY_REQUESTS, "INTENTOS_LIMITADOS", ERROR_VALIDACION);
            }
            throw excepcion;
        }
    }

    /** Indica si el cliente ya inició sesión sin mostrar datos de otras cuentas. */
    @GetMapping("/sesion")
    public ResponseEntity<RespuestaSesion> consultarSesion() {
        Authentication autenticacion = SecurityContextHolder.getContext().getAuthentication();
        if (autenticacion != null && autenticacion.isAuthenticated()
                && autenticacion.getPrincipal() instanceof PrincipalCliente principal) {
            return ResponseEntity.ok().headers(encabezadosPrivados()).body(
                    new RespuestaSesion(true, principal.cuentaId(), principal.correo(), "CLIENTE", null));
        }
        return ResponseEntity.ok().headers(encabezadosPrivados())
                .body(new RespuestaSesion(false, null, null, null, null));
    }

    /** Comprueba los datos de acceso del cliente y renueva los códigos que protegen su sesión. */
    @PostMapping("/sesion")
    public ResponseEntity<?> iniciarSesion(
            @RequestBody(required = false) SolicitudInicioSesion cuerpo,
            HttpServletRequest solicitud,
            HttpServletResponse respuesta) {
        if (cuerpo == null) {
            return error(HttpStatus.BAD_REQUEST, "VALIDACION", ERROR_VALIDACION);
        }
        if (existeOtraIdentidadAutenticada()) {
            return noAutenticado();
        }

        String correo = normalizarCorreo(cuerpo.correo());
        String claveIntentos = ValidadorClientes.crearClaveHash(correo);
        if (proteccionInicioSesion.estaBloqueado(claveIntentos)) {
            return error(HttpStatus.TOO_MANY_REQUESTS, "INTENTOS_LIMITADOS", ERROR_CREDENCIALES);
        }
        if (!ValidadorClientes.correoValido(correo) || cuerpo.contrasena() == null) {
            proteccionInicioSesion.registrarFallo(claveIntentos);
            return noAutenticado();
        }

        Authentication autenticacion;
        try {
            autenticacion = administradorAutenticacion.authenticate(
                    UsernamePasswordAuthenticationToken.unauthenticated(correo, cuerpo.contrasena()));
        } catch (DataAccessException excepcion) {
            return error(HttpStatus.SERVICE_UNAVAILABLE, "API_NO_DISPONIBLE", ERROR_SERVICIO);
        } catch (AuthenticationServiceException excepcion) {
            return error(HttpStatus.SERVICE_UNAVAILABLE, "API_NO_DISPONIBLE", ERROR_SERVICIO);
        } catch (AuthenticationException excepcion) {
            proteccionInicioSesion.registrarFallo(claveIntentos);
            return noAutenticado();
        }

        if (autenticacion == null || !(autenticacion.getPrincipal() instanceof PrincipalCliente principal)) {
            proteccionInicioSesion.registrarFallo(claveIntentos);
            return noAutenticado();
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
        proteccionInicioSesion.registrarExito(claveIntentos);
        String tokenCsrf = renovarTokenCsrf(solicitud, respuesta);
        return ResponseEntity.ok().headers(encabezadosPrivados()).body(new RespuestaSesion(
                true, principal.cuentaId(), principal.correo(), "CLIENTE", tokenCsrf));
    }

    /** Cierra la sesión actual del cliente y retira el dato que la mantenía abierta en el navegador. */
    @DeleteMapping("/sesion")
    public ResponseEntity<Void> cerrarSesion(HttpServletRequest solicitud, HttpServletResponse respuesta) {
        if (principalClienteActual() == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).headers(encabezadosPrivados()).build();
        }
        HttpSession sesion = solicitud.getSession(false);
        if (sesion != null) {
            gestorSesiones.olvidar(sesion);
        }
        SecurityContextHolder.clearContext();
        invalidar(sesion);
        expirarCookieCliente(solicitud, respuesta);
        return ResponseEntity.noContent().headers(encabezadosPrivados()).build();
    }

    /** Muestra al cliente sus datos y la información de su membresía usando la cuenta con la que entró. */
    @GetMapping("/portal")
    public ResponseEntity<PortalCliente> consultarPortal() {
        PrincipalCliente principal = principalClienteActual();
        if (principal == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).headers(encabezadosPrivados()).build();
        }
        return ResponseEntity.ok().headers(encabezadosPrivados())
                .body(servicioClientes.consultarPortal(principal.cuentaId()));
    }

    /** Cambia la contraseña y cierra todas las sesiones abiertas de esa cuenta de cliente. */
    @PatchMapping("/contrasena")
    public ResponseEntity<?> cambiarContrasena(
            @RequestBody(required = false) SolicitudCambioContrasena cuerpo,
            HttpServletRequest solicitud,
            HttpServletResponse respuesta) {
        PrincipalCliente principal = principalClienteActual();
        if (principal == null) {
            return noAutenticado();
        }
        if (cuerpo == null || !contrasenaActualValida(cuerpo.contrasenaActual())
                || !ValidadorClientes.contrasenaValida(cuerpo.nuevaContrasena())) {
            return error(HttpStatus.BAD_REQUEST, "VALIDACION", ERROR_VALIDACION);
        }

        servicioClientes.cambiarContrasena(
                principal.cuentaId(), cuerpo.contrasenaActual(), cuerpo.nuevaContrasena());
        gestorSesiones.revocarCuenta(principal.cuentaId());
        SecurityContextHolder.clearContext();
        expirarCookieCliente(solicitud, respuesta);
        return ResponseEntity.noContent().headers(encabezadosPrivados()).build();
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<RespuestaError> solicitudJsonNoValida() {
        return error(HttpStatus.BAD_REQUEST, "VALIDACION", ERROR_VALIDACION);
    }

    @ExceptionHandler(ErrorConfiguracion.class)
    public ResponseEntity<RespuestaError> errorOperacionCliente(ErrorConfiguracion excepcion) {
        String codigo = excepcion.codigo() == null ? "OPERACION_NO_COMPLETADA" : excepcion.codigo();
        return error(excepcion.estadoHttp(), codigo, excepcion.getMessage());
    }

    @ExceptionHandler(DataAccessException.class)
    public ResponseEntity<RespuestaError> errorPersistenciaCliente(DataAccessException excepcion) {
        return error(HttpStatus.SERVICE_UNAVAILABLE, "API_NO_DISPONIBLE", ERROR_SERVICIO);
    }

    @ExceptionHandler(TransactionException.class)
    public ResponseEntity<RespuestaError> errorTransaccionCliente(TransactionException excepcion) {
        return error(HttpStatus.SERVICE_UNAVAILABLE, "API_NO_DISPONIBLE", ERROR_SERVICIO);
    }

    private boolean contrasenaActualValida(String contrasena) {
        return ValidadorClientes.contrasenaActualValida(contrasena);
    }

    private String normalizarCorreo(String correo) {
        return ValidadorClientes.normalizarCorreo(correo);
    }

    private SolicitudRegistro validarRegistro(SolicitudRegistro cuerpo, String correo) {
        ValidadorClientes.DatosRegistro datos = ValidadorClientes.validarRegistro(
                cuerpo.nombres(), cuerpo.primerApellido(), cuerpo.segundoApellido(), correo,
                cuerpo.contrasena());
        if (datos == null) {
            return null;
        }
        return new SolicitudRegistro(datos.nombres(), datos.primerApellido(), datos.segundoApellido(),
                correo, cuerpo.contrasena());
    }

    private String renovarTokenCsrf(HttpServletRequest solicitud, HttpServletResponse respuesta) {
        repositorioCsrf.saveToken(null, solicitud, respuesta);
        CsrfToken token = repositorioCsrf.generateToken(solicitud);
        repositorioCsrf.saveToken(token, solicitud, respuesta);
        return token.getToken();
    }

    private boolean existeOtraIdentidadAutenticada() {
        Authentication autenticacion = SecurityContextHolder.getContext().getAuthentication();
        return autenticacion != null && autenticacion.isAuthenticated()
                && !(autenticacion.getPrincipal() instanceof PrincipalCliente)
                && !(autenticacion instanceof AnonymousAuthenticationToken);
    }

    private PrincipalCliente principalClienteActual() {
        Authentication autenticacion = SecurityContextHolder.getContext().getAuthentication();
        if (autenticacion == null || !autenticacion.isAuthenticated()
                || !(autenticacion.getPrincipal() instanceof PrincipalCliente principal)) {
            return null;
        }
        return principal;
    }

    private ResponseEntity<RespuestaError> noAutenticado() {
        return error(HttpStatus.UNAUTHORIZED, "CREDENCIALES_NO_VALIDAS", ERROR_CREDENCIALES);
    }

    private ResponseEntity<RespuestaError> error(HttpStatus estado, String codigo, String mensaje) {
        return ResponseEntity.status(estado).headers(encabezadosPrivados())
                .body(new RespuestaError(codigo, mensaje));
    }

    private static HttpHeaders encabezadosPrivados() {
        HttpHeaders encabezados = new HttpHeaders();
        encabezados.set(HttpHeaders.CACHE_CONTROL, "no-store, private");
        encabezados.set(HttpHeaders.VARY, "Cookie");
        return encabezados;
    }

    private static void invalidar(HttpSession sesion) {
        if (sesion != null) {
            try {
                sesion.invalidate();
            } catch (IllegalStateException excepcion) {
                // Otra solicitud pudo cerrar la misma sesión al mismo tiempo.
            }
        }
    }

    private static void expirarCookieCliente(HttpServletRequest solicitud, HttpServletResponse respuesta) {
        String cookie = "JSESSIONID=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict";
        respuesta.addHeader(HttpHeaders.SET_COOKIE, cookie + (solicitud.isSecure() ? "; Secure" : ""));
    }

    private record SolicitudRegistro(
            String nombres,
            String primerApellido,
            String segundoApellido,
            String correo,
            String contrasena) {
        @Override
        public String toString() {
            return "SolicitudRegistro[datos personales y credenciales redactados]";
        }
    }

    private record SolicitudInicioSesion(String correo, String contrasena) {
        @Override
        public String toString() {
            return "SolicitudInicioSesion[credenciales redactadas]";
        }
    }

    private record SolicitudCambioContrasena(String contrasenaActual, String nuevaContrasena) {
        @Override
        public String toString() {
            return "SolicitudCambioContrasena[credenciales redactadas]";
        }
    }

    private record RespuestaCsrf(String token) {
        @Override
        public String toString() {
            return "RespuestaCsrf[token redactado]";
        }
    }

    private record RespuestaRegistro(UUID clienteId, String correo) {
        @Override
        public String toString() {
            return "RespuestaRegistro[identidad redactada]";
        }
    }

    @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
    private record RespuestaSesion(
            boolean autenticada, UUID clienteId, String correo, String rol, String csrfToken) {
        @Override
        public String toString() {
            return "RespuestaSesion[datos de sesión redactados]";
        }
    }

    private record RespuestaError(String codigo, String error) {
    }
}
