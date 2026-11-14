package mx.smartparking.api.clientes.controlador;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import java.util.List;
import mx.smartparking.api.clientes.modelo.ClientePortal;
import mx.smartparking.api.clientes.modelo.EstadoMembresia;
import mx.smartparking.api.clientes.modelo.MembresiaPortal;
import mx.smartparking.api.clientes.modelo.PlanMembresia;
import mx.smartparking.api.clientes.modelo.PortalCliente;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.cliente.PrincipalCliente;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

@ExtendWith(MockitoExtension.class)
class ControladorClientesTest extends ControladorClientesTestSupport {

    @Test
    void loginCorrectoRotaSesionYCsrfYDevuelveSoloIdentidadCliente() throws Exception {
        MockHttpSession sesion = new MockHttpSession();
        String idAnterior = sesion.getId();
        var solicitudCsrf = new org.springframework.mock.web.MockHttpServletRequest();
        solicitudCsrf.setSession(sesion);
        var tokenAnterior = repositorioCsrf.generateToken(solicitudCsrf);
        repositorioCsrf.saveToken(tokenAnterior, solicitudCsrf,
                new org.springframework.mock.web.MockHttpServletResponse());
        var autenticacion = UsernamePasswordAuthenticationToken.authenticated(
                new PrincipalCliente(CLIENTE_ID, 1L, CORREO), null,
                List.of(new SimpleGrantedAuthority("ROLE_CLIENTE")));
        when(administradorAutenticacion.authenticate(any())).thenReturn(autenticacion);

        mvc.perform(post("/api/v1/clientes/sesion")
                        .session(sesion)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"correo":"CLIENTE@EXAMPLE.TEST","contrasena":"contraseña-segura"}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.autenticada").value(true))
                .andExpect(jsonPath("$.clienteId").value(CLIENTE_ID.toString()))
                .andExpect(jsonPath("$.correo").value(CORREO))
                .andExpect(jsonPath("$.rol").value("CLIENTE"))
                .andExpect(jsonPath("$.csrfToken").value(org.hamcrest.Matchers.not(tokenAnterior.getToken())));

        assertNotEquals(idAnterior, sesion.getId());
        assertTrue(gestorSesiones.estaRegistrada(
                sesion.getId(), new PrincipalCliente(CLIENTE_ID, 1L, CORREO)));
        verify(repositorioContexto).saveContext(any(), any(), any());
    }

    @Test
    void clienteSesionDevuelveAnonimoSinExponerSesionAdministrativa() throws Exception {
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        new PrincipalPropietario(3L, "dueno@example.test"), null, List.of()));

        mvc.perform(get("/api/v1/clientes/sesion"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.autenticada").value(false))
                .andExpect(jsonPath("$.clienteId").doesNotExist())
                .andExpect(jsonPath("$.correo").doesNotExist());
    }

    @Test
    void loginClienteNoReutilizaNiRotaUnaSesionAdministrativa() throws Exception {
        MockHttpSession sesionDueno = new MockHttpSession();
        String idDueno = sesionDueno.getId();
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        new PrincipalPropietario(3L, "dueno@example.test"), null,
                        List.of(new SimpleGrantedAuthority("ROLE_DUENO"))));

        mvc.perform(post("/api/v1/clientes/sesion")
                        .session(sesionDueno)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"correo":"cliente@example.test","contrasena":"contraseña-segura"}
                                """))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.codigo").value("CREDENCIALES_NO_VALIDAS"));

        assertFalse(sesionDueno.isInvalid());
        assertEquals(idDueno, sesionDueno.getId());
        assertTrue(SecurityContextHolder.getContext().getAuthentication().getPrincipal()
                instanceof PrincipalPropietario);
        verify(administradorAutenticacion, never()).authenticate(any());
    }

    @Test
    void loginIncorrectoEsGenericoYElSextoIntentoSeLimita() throws Exception {
        when(administradorAutenticacion.authenticate(any()))
                .thenThrow(new BadCredentialsException("detalle-autenticacion-secreto"));

        for (int intento = 0; intento < 5; intento++) {
            mvc.perform(post("/api/v1/clientes/sesion")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {"correo":"Cliente@Example.Test","contrasena":"clave-incorrecta"}
                                    """))
                    .andExpect(status().isUnauthorized())
                    .andExpect(jsonPath("$.codigo").value("CREDENCIALES_NO_VALIDAS"))
                    .andExpect(jsonPath("$.error").value("Correo o contraseña no válidos."));
        }
        mvc.perform(post("/api/v1/clientes/sesion")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"correo":"cliente@example.test","contrasena":"clave-incorrecta"}
                                """))
                .andExpect(status().isTooManyRequests())
                .andExpect(jsonPath("$.codigo").value("INTENTOS_LIMITADOS"));

        verify(administradorAutenticacion, org.mockito.Mockito.times(5)).authenticate(any());
    }

    @Test
    void portalUsaElIdDelPrincipalYNoUnoDelCliente() throws Exception {
        SecurityContextHolder.getContext().setAuthentication(autenticacionCliente(CLIENTE_ID));
        PortalCliente portal = new PortalCliente(
                new ClientePortal(CLIENTE_ID, "Ana", "Pérez", null, CORREO),
                new MembresiaPortal(EstadoMembresia.SIN_MEMBRESIA,
                        new PlanMembresia("prod", "price", "Membresía", 39900, "MXN", "month", 1)));
        when(servicioClientes.consultarPortal(CLIENTE_ID)).thenReturn(portal);

        mvc.perform(get("/api/v1/clientes/portal"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.cliente.clienteId").value(CLIENTE_ID.toString()))
                .andExpect(jsonPath("$.membresia.estado").value("SIN_MEMBRESIA"))
                .andExpect(jsonPath("$.membresia.plan.importeMenorUnidad").value(39900))
                .andExpect(header().string("Cache-Control", "no-store, private"));
        verify(servicioClientes).consultarPortal(CLIENTE_ID);
        verify(servicioClientes, never()).consultarPortal(OTRO_CLIENTE_ID);
    }

    @Test
    void cambioContrasenaRevocaSoloSesionesClienteYExpiraCookie() throws Exception {
        MockHttpSession sesionActual = new MockHttpSession();
        MockHttpSession sesionOtroCliente = new MockHttpSession();
        MockHttpSession sesionClienteAjeno = new MockHttpSession();
        gestorSesiones.registrar(sesionActual, new PrincipalCliente(CLIENTE_ID, 1L, CORREO));
        gestorSesiones.registrar(sesionOtroCliente, new PrincipalCliente(CLIENTE_ID, 1L, CORREO));
        gestorSesiones.registrar(sesionClienteAjeno,
                new PrincipalCliente(OTRO_CLIENTE_ID, 4L, "otro@example.test"));
        SecurityContextHolder.getContext().setAuthentication(autenticacionCliente(CLIENTE_ID));

        mvc.perform(patch("/api/v1/clientes/contrasena")
                        .session(sesionActual)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"contrasenaActual":"actual-segura","nuevaContrasena":"nueva-segura-123"}
                                """))
                .andExpect(status().isNoContent())
                .andExpect(header().string("Set-Cookie",
                        org.hamcrest.Matchers.containsString("JSESSIONID=; Path=/; Max-Age=0")));

        verify(servicioClientes).cambiarContrasena(CLIENTE_ID, "actual-segura", "nueva-segura-123");
        assertTrue(sesionActual.isInvalid());
        assertTrue(sesionOtroCliente.isInvalid());
        assertFalse(sesionClienteAjeno.isInvalid());
        assertTrue(gestorSesiones.estaRegistrada(
                sesionClienteAjeno.getId(), new PrincipalCliente(OTRO_CLIENTE_ID, 4L, "otro@example.test")));
    }

    @Test
    void intentoDeLogoutAdministrativoNoInvalidaSesionDueno() throws Exception {
        MockHttpSession sesion = new MockHttpSession();
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        new PrincipalPropietario(7L, "dueno@example.test"), null, List.of()));

        mvc.perform(delete("/api/v1/clientes/sesion").session(sesion))
                .andExpect(status().isUnauthorized());

        assertFalse(sesion.isInvalid());
    }
}
