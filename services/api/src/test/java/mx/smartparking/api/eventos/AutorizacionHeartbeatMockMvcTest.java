package mx.smartparking.api.eventos;

import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import jakarta.servlet.Filter;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.FilterChainProxy;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;

/** Comprueba que el ACK de heartbeat conserva sesión dueña y protección CSRF. */
@SpringBootTest(properties = {
        "spring.profiles.active=test",
        "spring.application.name=autorizacion-heartbeat-eventos-test",
        "server.address=127.0.0.1",
        "server.port=0",
        "spring.flyway.enabled=false",
        "spring.datasource.url=jdbc:postgresql://127.0.0.1:1/smartparking_test",
        "spring.datasource.username=test",
        "spring.datasource.password=test"
})
class AutorizacionHeartbeatMockMvcTest {

    private static final String ID_SUSCRIPCION = "00000000-0000-0000-0000-000000000001";
    private MockMvc mvc;

    @Autowired
    private WebApplicationContext contextoWeb;

    @Autowired
    private FilterChainProxy cadenaSeguridad;

    @Autowired
    private GestorSesionesPropietario gestorSesiones;

    @MockitoBean
    private RepositorioCuentas cuentas;

    @MockitoBean
    private ServicioEventosAdministracion servicioEventos;

    @BeforeEach
    void prepararMockMvc() {
        mvc = MockMvcBuilders.webAppContextSetup(contextoWeb)
                .addFilters((Filter) cadenaSeguridad)
                .build();
    }

    @Test
    void ackValidoRequiereYUsaLaSesionDuenaRegistrada() throws Exception {
        PrincipalPropietario dueno = nuevoDueno();
        MockHttpSession sesion = sesionAutenticada(dueno, true);
        when(cuentas.sesionVigente(dueno.cuentaId(), dueno.revisionAcceso(),
                dueno.rol().name(), dueno.revisionPropietario())).thenReturn(true);

        mvc.perform(post("/api/v1/eventos/administracion/heartbeat")
                        .session(sesion)
                        .with(csrf().asHeader())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"suscripcionId\":\"" + ID_SUSCRIPCION + "\",\"secuencia\":1}"))
                .andExpect(status().isNoContent())
                .andExpect(content().string(""));

        verify(servicioEventos).confirmarHeartbeat(sesion.getId(), dueno, ID_SUSCRIPCION, 1);
    }

    @Test
    void ackValidoAceptaLaSesionDeOperadorRegistrada() throws Exception {
        PrincipalPropietario operador = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.OPERADOR, 2, 1, "operador@example.test");
        MockHttpSession sesion = sesionAutenticada(operador, true);
        when(cuentas.sesionVigente(operador.cuentaId(), operador.revisionAcceso(),
                operador.rol().name(), operador.revisionPropietario())).thenReturn(true);

        mvc.perform(post("/api/v1/eventos/administracion/heartbeat")
                        .session(sesion)
                        .with(csrf().asHeader())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"suscripcionId\":\"" + ID_SUSCRIPCION + "\",\"secuencia\":1}"))
                .andExpect(status().isNoContent())
                .andExpect(content().string(""));

        verify(servicioEventos).confirmarHeartbeat(sesion.getId(), operador, ID_SUSCRIPCION, 1);
    }

    @Test
    void ackSinTokenCsrfEsRechazadoAntesDelServicio() throws Exception {
        PrincipalPropietario dueno = nuevoDueno();
        MockHttpSession sesion = sesionAutenticada(dueno, true);
        when(cuentas.sesionVigente(dueno.cuentaId(), dueno.revisionAcceso(),
                dueno.rol().name(), dueno.revisionPropietario())).thenReturn(true);

        mvc.perform(post("/api/v1/eventos/administracion/heartbeat")
                        .session(sesion)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"suscripcionId\":\"" + ID_SUSCRIPCION + "\",\"secuencia\":1}"))
                .andExpect(status().isForbidden());

        verifyNoInteractions(servicioEventos);
    }

    @Test
    void ackDeSesionNoRegistradaDevuelve401() throws Exception {
        PrincipalPropietario dueno = nuevoDueno();
        MockHttpSession sesion = sesionAutenticada(dueno, false);

        mvc.perform(post("/api/v1/eventos/administracion/heartbeat")
                        .session(sesion)
                        .with(csrf().asHeader())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"suscripcionId\":\"" + ID_SUSCRIPCION + "\",\"secuencia\":1}"))
                .andExpect(status().isUnauthorized());

        verifyNoInteractions(servicioEventos);
    }

    private PrincipalPropietario nuevoDueno() {
        return new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.DUENO, 1, 1, "dueno@example.test");
    }

    private MockHttpSession sesionAutenticada(PrincipalPropietario dueno, boolean registrar) {
        MockHttpSession sesion = new MockHttpSession();
        String autoridad = dueno.rol() == RolCuenta.DUENO ? "ROLE_DUENO" : "ROLE_OPERADOR";
        SecurityContext contexto = SecurityContextHolder.createEmptyContext();
        contexto.setAuthentication(UsernamePasswordAuthenticationToken.authenticated(
                dueno, null, List.of(new SimpleGrantedAuthority(autoridad))));
        sesion.setAttribute(HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY, contexto);
        if (registrar) {
            gestorSesiones.registrar(sesion, dueno);
        }
        return sesion;
    }
}
