package mx.smartparking.api.seguridad;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.csrf.CsrfFilter;

@ExtendWith(MockitoExtension.class)
class ControladorSesionPropietarioSesionTest extends ControladorSesionPropietarioTestSupport {

    @Test
    void filtroCsrfRechazaTokenAusenteOIncorrectoAntesDelLogin() throws Exception {
        MockHttpServletRequest solicitud = nuevaSolicitudConCsrf();
        solicitud.removeHeader("X-CSRF-TOKEN");
        MockHttpServletResponse respuesta = new MockHttpServletResponse();
        AtomicChain cadena = new AtomicChain();
        CsrfFilter filtro = new CsrfFilter(repositorioCsrf);

        filtro.doFilter(solicitud, respuesta, cadena);

        assertEquals(403, respuesta.getStatus());
        assertFalse(cadena.ejecutada);
        verify(administradorAutenticacion, never()).authenticate(any(Authentication.class));

        MockHttpServletRequest alterada = nuevaSolicitudConCsrf();
        alterada.setMethod("POST");
        alterada.setRequestURI("/api/v1/sesion");
        alterada.removeHeader("X-CSRF-TOKEN");
        alterada.addHeader("X-CSRF-TOKEN", repositorioCsrf.loadToken(alterada).getToken() + "-incorrecto");
        MockHttpServletResponse respuestaAlterada = new MockHttpServletResponse();
        AtomicChain cadenaAlterada = new AtomicChain();
        filtro.doFilter(alterada, respuestaAlterada, cadenaAlterada);

        assertEquals(403, respuestaAlterada.getStatus());
        assertFalse(cadenaAlterada.ejecutada);
        verify(administradorAutenticacion, never()).authenticate(any(Authentication.class));
    }

    @Test
    void errorTemporalDeBaseDeDatosNoExponeDetallesNiRegistraSesion() throws Exception {
        when(administradorAutenticacion.authenticate(any(Authentication.class)))
                .thenThrow(new DataAccessResourceFailureException("detalle-interno-secreto"));
        MockHttpServletRequest solicitud = nuevaSolicitudConCsrf();

        ResponseEntity<?> resultado = iniciarSesion(solicitud, CONTRASENA);

        assertEquals(503, resultado.getStatusCode().value());
        String respuesta = resultado.getBody().toString();
        assertTrue(respuesta.contains("No pudimos comprobar tu acceso en este momento. Inténtalo más tarde."));
        assertFalse(respuesta.contains("detalle-interno-secreto"));
        assertFalse(respuesta.contains(CONTRASENA));
        assertFalse(gestorSesiones.estaRegistrada(solicitud.getSession(false).getId(), 13L));
    }

    @Test
    void cierreDeSesionInvalidaLaSesionRegistradaYLimpiaElContexto() throws Exception {
        MockHttpServletRequest solicitud = nuevaSolicitudConCsrf();
        MockHttpServletResponse respuesta = new MockHttpServletResponse();
        MockHttpSession sesion = (MockHttpSession) solicitud.getSession(false);
        String tokenAnterior = repositorioCsrf.loadToken(solicitud).getToken();
        gestorSesiones.registrar(sesion, 13L);
        SecurityContextHolder.getContext().setAuthentication(UsernamePasswordAuthenticationToken.authenticated(
                new PrincipalPropietario(13L, CORREO), null, List.of()));

        controlador.cerrarSesion(solicitud, respuesta);

        assertTrue(sesion.isInvalid());
        assertFalse(gestorSesiones.estaRegistrada(sesion.getId(), 13L));
        assertNull(SecurityContextHolder.getContext().getAuthentication());
        assertNotEquals(tokenAnterior, repositorioCsrf.loadToken(solicitud).getToken());
    }
}
