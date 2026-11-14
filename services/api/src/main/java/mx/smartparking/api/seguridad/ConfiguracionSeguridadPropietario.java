package mx.smartparking.api.seguridad;

import jakarta.servlet.http.HttpServletResponse;
import java.util.Map;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpMethod;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.password.DelegatingPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.crypto.password.Pbkdf2PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.access.AccessDeniedHandler;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.security.web.context.SecurityContextHolderFilter;
import org.springframework.security.web.context.SecurityContextRepository;
import org.springframework.security.web.csrf.CsrfTokenRepository;
import org.springframework.security.web.csrf.CsrfTokenRequestAttributeHandler;
import org.springframework.security.web.csrf.HttpSessionCsrfTokenRepository;
import org.springframework.security.web.util.matcher.RequestMatcher;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.cliente.FiltroSesionCliente;
import mx.smartparking.api.seguridad.cliente.GestorSesionesCliente;
import mx.smartparking.api.seguridad.cliente.ProveedorAutenticacionCliente;
import org.springframework.security.web.csrf.CsrfFilter;

/** Establece cómo se comprueban las cuentas y se protegen sus sesiones y solicitudes. */
@Configuration
public class ConfiguracionSeguridadPropietario {

    private static final RequestMatcher WEBHOOK_STRIPE = solicitud ->
            HttpMethod.POST.matches(solicitud.getMethod())
                    && "/api/v1/webhooks/stripe".equals(solicitud.getServletPath());

    private static final String ID_HASH_PBKDF2 = "pbkdf2@SpringSecurity_v5_8_600k";
    private static final int ITERACIONES_PBKDF2 = 600_000;
    private static final int TAMANO_SAL_PBKDF2 = 16;

    /** Prepara una forma de proteger las contraseñas guardadas y conserva la versión del método utilizado. */
    @Bean
    public PasswordEncoder passwordEncoder() {
        Pbkdf2PasswordEncoder pbkdf2 = new Pbkdf2PasswordEncoder(
                "",
                TAMANO_SAL_PBKDF2,
                ITERACIONES_PBKDF2,
                Pbkdf2PasswordEncoder.SecretKeyFactoryAlgorithm.PBKDF2WithHmacSHA256);
        return new DelegatingPasswordEncoder(ID_HASH_PBKDF2, Map.of(ID_HASH_PBKDF2, pbkdf2));
    }

    @Bean
    public CsrfTokenRepository csrfTokenRepository() {
        HttpSessionCsrfTokenRepository repositorio = new HttpSessionCsrfTokenRepository();
        repositorio.setHeaderName("X-CSRF-TOKEN");
        return repositorio;
    }

    @Bean
    public SecurityContextRepository securityContextRepository() {
        return new HttpSessionSecurityContextRepository();
    }

    @Bean
    @Primary
    public AuthenticationManager authenticationManager(ProveedorAutenticacionPropietario proveedor) {
        return proveedor::authenticate;
    }

    @Bean("clienteAuthenticationManager")
    public AuthenticationManager clienteAuthenticationManager(ProveedorAutenticacionCliente proveedor) {
        return proveedor::authenticate;
    }

    @Bean
    @Order(3)
    public SecurityFilterChain filtroSeguridadPropietario(
            HttpSecurity http,
            CsrfTokenRepository repositorioCsrf,
            SecurityContextRepository repositorioContexto,
            AuthenticationManager administradorAutenticacion,
            GestorSesionesPropietario gestorSesiones,
            GestorSesionesCliente gestorSesionesCliente,
            RepositorioCuentas cuentas) throws Exception {
        AuthenticationEntryPoint puntoEntrada = (solicitud, respuesta, excepcion) -> escribirError(
                respuesta, HttpServletResponse.SC_UNAUTHORIZED, "SESION_NO_VIGENTE",
                "Inicia sesión para continuar.");
        AccessDeniedHandler accesoDenegado = (solicitud, respuesta, excepcion) -> {
            String codigo = excepcion instanceof org.springframework.security.web.csrf.CsrfException
                    ? "CSRF_RECHAZADO" : "PERMISO_INSUFICIENTE";
            escribirError(respuesta, HttpServletResponse.SC_FORBIDDEN, codigo,
                    "No tienes acceso para hacer este cambio.");
        };

        http
                .authenticationManager(administradorAutenticacion)
                .securityContext(contexto -> contexto
                        .securityContextRepository(repositorioContexto)
                        .requireExplicitSave(true))
                .sessionManagement(sesiones -> sesiones
                        .sessionCreationPolicy(SessionCreationPolicy.IF_REQUIRED)
                        .sessionFixation(fijacion -> fijacion.changeSessionId()))
                .csrf(csrf -> csrf
                        .csrfTokenRepository(repositorioCsrf)
                        .csrfTokenRequestHandler(new CsrfTokenRequestAttributeHandler())
                        .ignoringRequestMatchers(WEBHOOK_STRIPE))
                .exceptionHandling(errores -> errores
                        .authenticationEntryPoint(puntoEntrada)
                        .accessDeniedHandler(accesoDenegado))
                .requestCache(AbstractHttpConfigurer::disable)
                .formLogin(AbstractHttpConfigurer::disable)
                .httpBasic(AbstractHttpConfigurer::disable)
                .logout(AbstractHttpConfigurer::disable)
                .rememberMe(AbstractHttpConfigurer::disable)
                .authorizeHttpRequests(autorizacion -> autorizacion
                        .requestMatchers(HttpMethod.GET,
                                "/api/v1/configuracion/estado",
                                "/api/v1/csrf",
                                "/api/v1/sesion",
                                "/api/v1/clientes/csrf",
                                "/api/v1/clientes/sesion",
                                "/actuator/health",
                                "/actuator/health/**").permitAll()
                        .requestMatchers(HttpMethod.POST,
                                "/api/v1/clientes/membresia/checkout").hasRole("CLIENTE")
                        .requestMatchers(HttpMethod.GET,
                                "/api/v1/clientes/membresia/checkout/*").hasRole("CLIENTE")
                        .requestMatchers(WEBHOOK_STRIPE).permitAll()
                        .requestMatchers(HttpMethod.POST,
                                "/api/v1/configuracion/inicial",
                                "/api/v1/sesion",
                                "/api/v1/transferencia/recuperar",
                                "/api/v1/transferencia/completar",
                                "/api/v1/operadores/activacion/validar",
                                "/api/v1/operadores/activacion/completar",
                                "/api/v1/operadores/recuperacion/validar",
                                "/api/v1/operadores/recuperacion/completar",
                                "/api/v1/clientes/registro",
                                "/api/v1/clientes/sesion").permitAll()
                        .requestMatchers(HttpMethod.DELETE, "/api/v1/sesion").authenticated()
                        .requestMatchers(HttpMethod.DELETE, "/api/v1/clientes/sesion").hasRole("CLIENTE")
                        .requestMatchers(HttpMethod.GET, "/api/v1/clientes/portal").hasRole("CLIENTE")
                        .requestMatchers(HttpMethod.PATCH, "/api/v1/clientes/contrasena").hasRole("CLIENTE")
                        .requestMatchers(HttpMethod.GET, "/api/v1/panel").hasRole("DUENO")
                        .requestMatchers(HttpMethod.GET, "/api/v1/empleados").hasRole("DUENO")
                        .requestMatchers(HttpMethod.GET, "/api/v1/eventos/administracion")
                                .hasAnyRole("DUENO", "OPERADOR")
                        .requestMatchers(HttpMethod.POST, "/api/v1/eventos/administracion/heartbeat")
                                .hasAnyRole("DUENO", "OPERADOR")
                        .requestMatchers(HttpMethod.GET,
                                "/api/v1/vision/cajones",
                                "/api/v1/accesos/historial",
                                "/api/v1/accesos/capacidad",
                                "/api/v1/accesos/dentro",
                                "/api/v1/accesos/salidas-manuales/capacidad",
                                "/api/v1/accesos/salidas-manuales/*",
                                "/api/v1/clientes/administracion",
                                "/api/v1/clientes/administracion/*",
                                "/api/v1/tarjetas-rfid/modalidad",
                                "/api/v1/tarjetas-rfid/personas",
                                "/api/v1/tarjetas-rfid",
                                "/api/v1/tarjetas-rfid/*",
                                "/api/v1/rfid-1/estado-conexion",
                                "/api/v1/rfid-1/capturas/activa",
                                "/api/v1/rfid-1/capturas/*",
                                "/api/v1/rfid-1/capturas/*/vista-previa").hasAnyRole("DUENO", "OPERADOR")
                        .requestMatchers(HttpMethod.PUT, "/api/v1/vision/cajones/*/display-name")
                                .hasAnyRole("DUENO", "OPERADOR")
                        .requestMatchers(HttpMethod.POST,
                                "/api/v1/accesos/movimientos/*/salida-manual",
                                "/api/v1/tarjetas-rfid/*/cancelacion",
                                "/api/v1/rfid-1/capturas",
                                "/api/v1/rfid-1/capturas/*/confirmacion").hasAnyRole("DUENO", "OPERADOR")
                        .requestMatchers(HttpMethod.DELETE, "/api/v1/rfid-1/capturas/*")
                                .hasAnyRole("DUENO", "OPERADOR")
                        .requestMatchers(HttpMethod.POST, "/api/v1/empleados").hasRole("DUENO")
                        .requestMatchers(HttpMethod.PATCH, "/api/v1/empleados/*/estado").hasRole("DUENO")
                        .requestMatchers(HttpMethod.PATCH,
                                "/api/v1/estacionamiento", "/api/v1/estacionamiento/datos").hasRole("DUENO")
                        .requestMatchers(HttpMethod.POST, "/api/v1/transferencia/iniciar").hasRole("DUENO")
                        .requestMatchers("/api/v1/dispositivos/**").denyAll()
                        .anyRequest().hasRole("DUENO"))
                .addFilterBefore(new FiltroLimiteCuerpoJson(), CsrfFilter.class)
                .addFilterAfter(new FiltroDiagnosticoSesion(), SecurityContextHolderFilter.class)
                .addFilterAfter(new FiltroSesionPropietario(gestorSesiones, cuentas), FiltroDiagnosticoSesion.class)
                .addFilterAfter(new FiltroSesionCliente(gestorSesionesCliente, cuentas), FiltroSesionPropietario.class);

        return http.build();
    }

    private static void escribirError(
            jakarta.servlet.http.HttpServletResponse respuesta,
            int estado,
            String codigo,
            String mensaje) throws java.io.IOException {
        respuesta.setStatus(estado);
        respuesta.setContentType("application/json");
        respuesta.setCharacterEncoding("UTF-8");
        respuesta.setHeader("Cache-Control", "no-store, private");
        respuesta.setHeader("Vary", "Cookie");
        respuesta.getWriter().write("{\"codigo\":\"" + codigo
                + "\",\"error\":\"" + mensaje + "\"}");
    }
}
