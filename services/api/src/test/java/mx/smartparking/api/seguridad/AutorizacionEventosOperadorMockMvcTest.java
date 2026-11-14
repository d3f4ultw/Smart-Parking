package mx.smartparking.api.seguridad;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import jakarta.servlet.Filter;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
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

/** Comprueba que el acceso operativo permita SSE y mantenga el directorio general cerrado. */
@SpringBootTest(properties = {
        "spring.profiles.active=test",
        "spring.application.name=autorizacion-eventos-operador-test",
        "server.address=127.0.0.1",
        "server.port=0",
        "spring.flyway.enabled=false",
        "spring.datasource.url=jdbc:postgresql://127.0.0.1:1/smartparking_test",
        "spring.datasource.username=test",
        "spring.datasource.password=test"
})
class AutorizacionEventosOperadorMockMvcTest {

    private MockMvc mvc;

    @Autowired
    private WebApplicationContext contextoWeb;

    @Autowired
    private FilterChainProxy cadenaSeguridad;

    @Autowired
    private GestorSesionesPropietario gestorSesiones;

    @MockitoBean
    private RepositorioCuentas cuentas;

    @BeforeEach
    void prepararMockMvc() {
        mvc = MockMvcBuilders.webAppContextSetup(contextoWeb)
                .addFilters((Filter) cadenaSeguridad)
                .build();
    }

    @Test
    void operadorSoloRecibe403EnElDirectorioGeneralYPuedeAbrirElStream() throws Exception {
        PrincipalPropietario operador = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.OPERADOR, 1, 1, "operador@example.test");
        MockHttpSession sesion = new MockHttpSession();
        SecurityContext contexto = SecurityContextHolder.createEmptyContext();
        contexto.setAuthentication(UsernamePasswordAuthenticationToken.authenticated(
                operador, null, List.of(new SimpleGrantedAuthority("ROLE_OPERADOR"))));
        sesion.setAttribute(HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY, contexto);
        gestorSesiones.registrar(sesion, operador);
        when(cuentas.sesionVigente(operador.cuentaId(), operador.revisionAcceso(),
                operador.rol().name(), operador.revisionPropietario())).thenReturn(true);

        mvc.perform(get("/api/v1/empleados").session(sesion))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.codigo").value("PERMISO_INSUFICIENTE"));

        mvc.perform(get("/api/v1/eventos/administracion").session(sesion))
                .andExpect(status().isOk())
                .andExpect(request().asyncStarted());

        PrincipalPropietario dueno = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.DUENO, 1, 1, "dueno@example.test");
        MockHttpSession sesionDueno = new MockHttpSession();
        SecurityContext contextoDueno = SecurityContextHolder.createEmptyContext();
        contextoDueno.setAuthentication(UsernamePasswordAuthenticationToken.authenticated(
                dueno, null, List.of(new SimpleGrantedAuthority("ROLE_DUENO"))));
        sesionDueno.setAttribute(HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY, contextoDueno);
        gestorSesiones.registrar(sesionDueno, dueno);
        when(cuentas.sesionVigente(dueno.cuentaId(), dueno.revisionAcceso(),
                dueno.rol().name(), dueno.revisionPropietario())).thenReturn(true);

        mvc.perform(get("/api/v1/eventos/administracion").session(sesionDueno))
                .andExpect(status().isOk())
                .andExpect(request().asyncStarted());
    }
}
