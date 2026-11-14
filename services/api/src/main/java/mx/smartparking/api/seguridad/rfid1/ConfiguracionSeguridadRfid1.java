package mx.smartparking.api.seguridad.rfid1;

import java.util.regex.Pattern;
import mx.smartparking.api.seguridad.FiltroLimiteCuerpoJson;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.AnonymousAuthenticationFilter;
import org.springframework.security.web.context.NullSecurityContextRepository;
import org.springframework.security.web.util.matcher.RequestMatcher;

/** Protege el acceso del dispositivo de forma independiente de las sesiones de las personas. */
@Configuration
public class ConfiguracionSeguridadRfid1 {

    private static final String RUTA_LECTURAS = "/api/v1/dispositivos/rfid-1/lecturas";
    private static final String RUTA_ENTRADAS_RFID2 = "/api/v1/dispositivos/rfid-2/entradas";
    private static final String RUTA_SALIDAS_RFID3 = "/api/v1/dispositivos/rfid-3/salidas";
    private static final String PREFIJO_MANUAL = "/api/v1/dispositivos/rfid-3/salidas-manuales/";
    private static final String RUTA_ESTADO_DISPOSITIVO = "/api/v1/dispositivos/rfid-1/estado";
    private static final String RUTA_CAPTURA_ACTIVA = "/api/v1/dispositivos/rfid-1/capturas/activa";
    private static final Pattern RUTA_ESTADO_CAPTURA = Pattern.compile(
            "/api/v1/dispositivos/rfid-1/capturas/[0-9a-f]{32}/estado");

    private static final RequestMatcher SOLICITUDES_DISPOSITIVO = solicitud -> {
        String ruta = rutaSinContexto(solicitud);
        // Toda variante de esta ruta debe pasar por el filtro del dispositivo,
        // incluso si contiene un identificador inválido o usa otro método.
        if (ruta.startsWith(PREFIJO_MANUAL)
                || solicitud.getServletPath().startsWith(PREFIJO_MANUAL)) {
            return true;
        }
        if (HttpMethod.GET.matches(solicitud.getMethod())) {
            return RUTA_CAPTURA_ACTIVA.equals(ruta);
        }
        if (!HttpMethod.POST.matches(solicitud.getMethod())) {
            return false;
        }
        return RUTA_LECTURAS.equals(ruta)
                || RUTA_ENTRADAS_RFID2.equals(ruta)
                || RUTA_SALIDAS_RFID3.equals(ruta)
                || RUTA_ESTADO_DISPOSITIVO.equals(ruta)
                || RUTA_ESTADO_CAPTURA.matcher(ruta).matches();
    };

    @Bean
    public AutenticadorDispositivoRfid1 autenticadorDispositivoRfid1(
            @Value("${smartparking.rfid1.token-sha256:}") String hashToken) {
        return new AutenticadorDispositivoRfid1(hashToken);
    }

    @Bean
    @Order(1)
    public SecurityFilterChain filtroSeguridadRfid1(
            HttpSecurity http,
            AutenticadorDispositivoRfid1 autenticador) throws Exception {
        FiltroAutenticacionDispositivoRfid1 filtro = new FiltroAutenticacionDispositivoRfid1(autenticador);

        http.securityMatcher(SOLICITUDES_DISPOSITIVO)
                .securityContext(contexto -> contexto
                        .securityContextRepository(new NullSecurityContextRepository())
                        .requireExplicitSave(true))
                .sessionManagement(sesiones -> sesiones
                        .sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .csrf(AbstractHttpConfigurer::disable)
                .requestCache(AbstractHttpConfigurer::disable)
                .formLogin(AbstractHttpConfigurer::disable)
                .httpBasic(AbstractHttpConfigurer::disable)
                .logout(AbstractHttpConfigurer::disable)
                .authorizeHttpRequests(autorizacion -> autorizacion
                        .anyRequest().hasAuthority("DISPOSITIVO_RFID1"))
                .addFilterBefore(filtro, AnonymousAuthenticationFilter.class)
                .addFilterAfter(new FiltroLimiteCuerpoJson(), FiltroAutenticacionDispositivoRfid1.class);

        return http.build();
    }

    private static String rutaSinContexto(jakarta.servlet.http.HttpServletRequest solicitud) {
        String ruta = solicitud.getRequestURI();
        String contexto = solicitud.getContextPath();
        return contexto == null || contexto.isEmpty() || !ruta.startsWith(contexto)
                ? ruta : ruta.substring(contexto.length());
    }
}
