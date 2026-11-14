package mx.smartparking.api.seguridad.vision;

import java.util.regex.Pattern;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpSession;
import mx.smartparking.api.seguridad.FiltroLimiteCuerpoJson;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.AnonymousAuthenticationFilter;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.security.web.context.NullSecurityContextRepository;
import org.springframework.security.web.util.matcher.RequestMatcher;

/** Protege las comunicaciones de la cámara de forma independiente de los accesos de personas y lectores. */
@Configuration
public class ConfiguracionSeguridadVision {
    private static final Pattern RUTA_CALIBRACION = Pattern.compile(
            "^/api/v1/vision/fuentes/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                    + "[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/calibracion$");
    private static final RequestMatcher SOLICITUDES_VISION = solicitud -> {
        String ruta = rutaSinContexto(solicitud);
        boolean publicacion = HttpMethod.POST.matches(solicitud.getMethod())
                && ("/api/v1/dispositivos/vision/sesiones".equals(ruta)
                || "/api/v1/dispositivos/vision/observaciones".equals(ruta));
        boolean calibracion = (HttpMethod.GET.matches(solicitud.getMethod())
                || HttpMethod.PUT.matches(solicitud.getMethod())) && RUTA_CALIBRACION.matcher(ruta).matches();
        return publicacion || (calibracion && !sesionOperador(solicitud));
    };

    @Bean
    @Order(2)
    public SecurityFilterChain filtroSeguridadVision(
            HttpSecurity http,
            @Value("${smartparking.vision.token-sha256:}") String hashToken,
            @Value("${smartparking.vision.fuente-id:}") String fuenteId,
            @Value("${smartparking.rfid1.token-sha256:}") String hashRfid) throws Exception {
        FiltroAutenticacionVision filtro = new FiltroAutenticacionVision(hashToken, fuenteId, hashRfid);
        http.securityMatcher(SOLICITUDES_VISION)
                .securityContext(contexto -> contexto
                        .securityContextRepository(new NullSecurityContextRepository())
                        .requireExplicitSave(true))
                .sessionManagement(sesiones -> sesiones.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .csrf(AbstractHttpConfigurer::disable)
                .requestCache(AbstractHttpConfigurer::disable)
                .formLogin(AbstractHttpConfigurer::disable)
                .httpBasic(AbstractHttpConfigurer::disable)
                .logout(AbstractHttpConfigurer::disable)
                .authorizeHttpRequests(autorizacion -> autorizacion.anyRequest().hasAuthority("DISPOSITIVO_VISION"))
                .addFilterBefore(filtro, AnonymousAuthenticationFilter.class)
                .addFilterAfter(new FiltroLimiteCuerpoJson(), FiltroAutenticacionVision.class);
        return http.build();
    }

    private static String rutaSinContexto(HttpServletRequest solicitud) {
        String ruta = solicitud.getRequestURI();
        String contexto = solicitud.getContextPath();
        return contexto == null || contexto.isEmpty() || !ruta.startsWith(contexto)
                ? ruta : ruta.substring(contexto.length());
    }

    private static boolean sesionOperador(HttpServletRequest solicitud) {
        HttpSession sesion = solicitud.getSession(false);
        if (sesion == null) {
            return false;
        }
        Object atributo = sesion.getAttribute(HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY);
        if (!(atributo instanceof SecurityContext contexto)) {
            return false;
        }
        Authentication autenticacion = contexto.getAuthentication();
        return autenticacion != null && autenticacion.isAuthenticated()
                && autenticacion.getPrincipal() instanceof PrincipalPropietario principal
                && principal.rol() == RolCuenta.OPERADOR;
    }
}
