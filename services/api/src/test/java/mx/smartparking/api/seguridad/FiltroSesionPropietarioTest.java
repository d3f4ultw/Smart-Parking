package mx.smartparking.api.seguridad;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import java.io.IOException;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

@ExtendWith(MockitoExtension.class)
class FiltroSesionPropietarioTest {

    @Mock
    private GestorSesionesPropietario gestorSesiones;

    @AfterEach
    void limpiarContexto() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void sesionRevocadaPorCambioDeRevisionDevuelve401EInvalidaElAcceso() throws Exception {
        MockHttpSession sesion = new MockHttpSession();
        MockHttpServletRequest solicitud = solicitudAutenticada(sesion, 8L);
        MockHttpServletResponse respuesta = new MockHttpServletResponse();
        AtomicBoolean cadenaEjecutada = new AtomicBoolean();
        when(gestorSesiones.estaRegistrada(org.mockito.ArgumentMatchers.eq(sesion.getId()),
                org.mockito.ArgumentMatchers.any(PrincipalPropietario.class)))
                .thenReturn(false);

        new FiltroExpuesto(gestorSesiones).ejecutar(
                solicitud,
                respuesta,
                (peticion, salida) -> cadenaEjecutada.set(true));

        assertEquals(401, respuesta.getStatus());
        assertTrue(respuesta.getHeader("Cache-Control").contains("no-store"));
        assertTrue(respuesta.getContentAsString().contains("La sesión no está vigente."));
        assertFalse(cadenaEjecutada.get());
        assertTrue(sesion.isInvalid());
        verify(gestorSesiones).olvidar(sesion);
        assertEquals(null, SecurityContextHolder.getContext().getAuthentication());
    }

    @Test
    void sesionRegistradaYVigenteContinuaLaPeticion() throws Exception {
        MockHttpSession sesion = new MockHttpSession();
        MockHttpServletRequest solicitud = solicitudAutenticada(sesion, 8L);
        MockHttpServletResponse respuesta = new MockHttpServletResponse();
        AtomicBoolean cadenaEjecutada = new AtomicBoolean();
        when(gestorSesiones.estaRegistrada(org.mockito.ArgumentMatchers.eq(sesion.getId()),
                org.mockito.ArgumentMatchers.any(PrincipalPropietario.class)))
                .thenReturn(true);

        new FiltroExpuesto(gestorSesiones).ejecutar(
                solicitud,
                respuesta,
                (peticion, salida) -> cadenaEjecutada.set(true));

        assertTrue(cadenaEjecutada.get());
        assertEquals(200, respuesta.getStatus());
        assertFalse(sesion.isInvalid());
        verify(gestorSesiones, never()).olvidar(sesion);
    }

    private MockHttpServletRequest solicitudAutenticada(MockHttpSession sesion, long revision) {
        MockHttpServletRequest solicitud = new MockHttpServletRequest();
        solicitud.setSession(sesion);
        SecurityContextHolder.getContext().setAuthentication(UsernamePasswordAuthenticationToken.authenticated(
                new PrincipalPropietario(revision, "duena@example.test"), null, List.of()));
        return solicitud;
    }

    private static final class FiltroExpuesto extends FiltroSesionPropietario {

        FiltroExpuesto(GestorSesionesPropietario gestorSesiones) {
            super(gestorSesiones);
        }

        void ejecutar(
                MockHttpServletRequest solicitud,
                MockHttpServletResponse respuesta,
                FilterChain cadena) throws ServletException, IOException {
            doFilterInternal(solicitud, respuesta, cadena);
        }
    }
}
