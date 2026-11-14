package mx.smartparking.api.seguridad;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.mockito.Mock;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.context.SecurityContextRepository;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.security.web.csrf.HttpSessionCsrfTokenRepository;

/** Fixture compartido por las suites de ControladorSesionPropietarioTest. */
abstract class ControladorSesionPropietarioTestSupport {
     static final String CORREO = "duena@example.test";
     static final String CORREO_OPERADOR = "operador@example.test";
     static final String CONTRASENA = "contrasena-de-acceso";

    @Mock
     AuthenticationManager administradorAutenticacion;

    @Mock
     SecurityContextRepository repositorioContexto;

    @Mock
     RepositorioCuentas cuentas;

     HttpSessionCsrfTokenRepository repositorioCsrf;
     GestorSesionesPropietario gestorSesiones;
     ProteccionIntentosInicioSesion proteccionIntentos;
     ControladorSesionPropietario controlador;

    @BeforeEach
    void preparar() {
        repositorioCsrf = new HttpSessionCsrfTokenRepository();
        gestorSesiones = new GestorSesionesPropietario();
        proteccionIntentos = new ProteccionIntentosInicioSesion();
        controlador = new ControladorSesionPropietario(
                administradorAutenticacion,
                repositorioContexto,
                repositorioCsrf,
                gestorSesiones,
                proteccionIntentos,
                cuentas);
    }

    @AfterEach
    void limpiarContexto() {
        SecurityContextHolder.clearContext();
    }



     MockHttpServletRequest nuevaSolicitudConCsrf() {
        MockHttpServletRequest solicitud = new MockHttpServletRequest();
        solicitud.setMethod("POST");
        solicitud.setRequestURI("/api/v1/sesion");
        CsrfToken token = repositorioCsrf.generateToken(solicitud);
        repositorioCsrf.saveToken(token, solicitud, new MockHttpServletResponse());
        solicitud.addHeader(token.getHeaderName(), token.getToken());
        return solicitud;
    }

     ResponseEntity<?> iniciarSesion(MockHttpServletRequest solicitud, String contrasena) throws Exception {
        return iniciarSesion(solicitud, CORREO, contrasena);
    }

     ResponseEntity<?> iniciarSesion(
            MockHttpServletRequest solicitud, String correo, String contrasena) throws Exception {
        Class<?> tipoCuerpo = java.util.Arrays.stream(ControladorSesionPropietario.class.getDeclaredClasses())
                .filter(tipo -> tipo.getSimpleName().equals("SolicitudInicioSesion"))
                .findFirst()
                .orElseThrow();
        Constructor<?> constructor = tipoCuerpo.getDeclaredConstructor(String.class, String.class);
        constructor.setAccessible(true);
        Object cuerpo = constructor.newInstance(correo, contrasena);
        Method metodo = ControladorSesionPropietario.class.getMethod(
                "iniciarSesion", tipoCuerpo, jakarta.servlet.http.HttpServletRequest.class,
                jakarta.servlet.http.HttpServletResponse.class);
        return (ResponseEntity<?>) metodo.invoke(controlador, cuerpo, solicitud, new MockHttpServletResponse());
    }

     static final class AtomicChain implements FilterChain {

         boolean ejecutada;

        @Override
        public void doFilter(jakarta.servlet.ServletRequest solicitud, jakarta.servlet.ServletResponse respuesta)
                throws IOException, ServletException {
            ejecutada = true;
        }
    }
}
