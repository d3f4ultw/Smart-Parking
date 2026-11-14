package mx.smartparking.api.seguridad.cliente;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import jakarta.servlet.FilterChain;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

@ExtendWith(MockitoExtension.class)
class FiltroSesionClienteTest {

    private static final UUID CUENTA_ID = UUID.fromString("ea6fdffb-c40c-4316-9080-422ac1b88657");
    private static final String CORREO = "cliente@example.test";

    @Mock
    private RepositorioCuentas cuentas;

    private GestorSesionesCliente gestor;
    private PrincipalCliente principal;
    private MockHttpSession sesion;
    private FiltroSesionCliente filtro;

    @BeforeEach
    void preparar() {
        gestor = new GestorSesionesCliente();
        principal = new PrincipalCliente(CUENTA_ID, 5L, CORREO);
        sesion = new MockHttpSession();
        gestor.registrar(sesion, principal);
        filtro = new FiltroSesionCliente(gestor, cuentas);
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(principal, null,
                        List.of(new SimpleGrantedAuthority("ROLE_CLIENTE"))));
    }

    @AfterEach
    void limpiarContexto() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void sesionVigenteConsultaLaCuentaYContinuaLaPeticion() throws Exception {
        when(cuentas.sesionVigente(CUENTA_ID, 5L, RolCuenta.CLIENTE.name(), 0L)).thenReturn(true);
        MockHttpServletRequest solicitud = solicitudConSesion();
        MockHttpServletResponse respuesta = new MockHttpServletResponse();
        boolean[] cadenaEjecutada = {false};

        filtro.doFilter(solicitud, respuesta, (peticion, salida) -> cadenaEjecutada[0] = true);

        assertTrue(cadenaEjecutada[0]);
        verify(cuentas).sesionVigente(CUENTA_ID, 5L, "CLIENTE", 0L);
    }

    @Test
    void sesionRevocadaInvalidaLaCookieClienteYDevuelve401() throws Exception {
        when(cuentas.sesionVigente(CUENTA_ID, 5L, RolCuenta.CLIENTE.name(), 0L)).thenReturn(false);
        MockHttpServletResponse respuesta = new MockHttpServletResponse();
        boolean[] cadenaEjecutada = {false};

        filtro.doFilter(solicitudConSesion(), respuesta,
                (peticion, salida) -> cadenaEjecutada[0] = true);

        assertFalse(cadenaEjecutada[0]);
        assertTrue(sesion.isInvalid());
        assertTrue(respuesta.getStatus() == 401);
        assertTrue(respuesta.getHeader("Set-Cookie").contains("JSESSIONID=; Path=/; Max-Age=0"));
        assertTrue(respuesta.getHeader("Cache-Control").contains("no-store, private"));
        assertTrue("Cookie".equals(respuesta.getHeader("Vary")));
        assertTrue(respuesta.getContentAsString().contains("SESION_NO_VIGENTE"));
        assertTrue(SecurityContextHolder.getContext().getAuthentication() == null);
    }

    @Test
    void fallaTemporalDeBaseNoExpiraLaSesionDelCliente() throws Exception {
        when(cuentas.sesionVigente(CUENTA_ID, 5L, RolCuenta.CLIENTE.name(), 0L))
                .thenThrow(new DataAccessResourceFailureException("detalle-interno"));
        MockHttpServletResponse respuesta = new MockHttpServletResponse();

        filtro.doFilter(solicitudConSesion(), respuesta, (peticion, salida) -> {
            throw new AssertionError("La petición no debe continuar con una sesión no comprobada.");
        });

        assertFalse(sesion.isInvalid());
        assertTrue(respuesta.getStatus() == 503);
        assertTrue(respuesta.getHeader("Set-Cookie") == null);
        assertFalse(respuesta.getContentAsString().contains("detalle-interno"));
        assertTrue(SecurityContextHolder.getContext().getAuthentication() != null);
    }

    private MockHttpServletRequest solicitudConSesion() {
        MockHttpServletRequest solicitud = new MockHttpServletRequest();
        solicitud.setMethod("GET");
        solicitud.setRequestURI("/api/v1/clientes/portal");
        solicitud.setSession(sesion);
        return solicitud;
    }
}
