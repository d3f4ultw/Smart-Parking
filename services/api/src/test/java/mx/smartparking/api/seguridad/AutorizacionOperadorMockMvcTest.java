package mx.smartparking.api.seguridad;

import static org.mockito.Mockito.when;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;

import jakarta.servlet.http.HttpSession;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import jakarta.servlet.Filter;
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
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;

/** Comprueba que la ruta de dueño rechace una sesión válida de operador. */
@SpringBootTest(properties = {
        "spring.profiles.active=test",
        "spring.application.name=autorizacion-operador-test",
        "server.address=127.0.0.1",
        "server.port=0",
        "spring.flyway.enabled=false",
        "spring.datasource.url=jdbc:postgresql://127.0.0.1:1/smartparking_test",
        "spring.datasource.username=test",
        "spring.datasource.password=test"
})
class AutorizacionOperadorMockMvcTest {

    private static final String CAPTURA_ID = "00112233445566778899aabbccddeeff";

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
    void sesionOperadorVigenteRecibe403AlConsultarPanelDeDueno() throws Exception {
        OperadorSesion operador = crearSesionOperador();
        when(cuentas.sesionVigente(operador.cuentaId(), operador.revisionAcceso(),
                operador.rol().name(), operador.revisionPropietario())).thenReturn(true);

        mvc.perform(get("/api/v1/panel").session(operador.sesion()))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.codigo").value("PERMISO_INSUFICIENTE"));
    }

    @Test
    void operadorAccedeSoloALasRutasAprobadasYSeMantienenCerradosEmpleadosYOperadores() throws Exception {
        OperadorSesion operador = crearSesionOperador();
        PrincipalPropietario principal = operador.principal();
        MockHttpSession sesion = operador.sesion();
        when(cuentas.sesionVigente(principal.cuentaId(), principal.revisionAcceso(),
                principal.rol().name(), principal.revisionPropietario())).thenReturn(true);

        assertNoRecibeForbidden(get("/api/v1/vision/cajones").session(sesion));
        assertNoRecibeForbidden(put("/api/v1/vision/cajones/{id}/display-name", UUID.randomUUID())
                .session(sesion).with(csrf()).contentType(MediaType.APPLICATION_JSON).content("{\"displayName\":\"A-1\"}"));
        assertNoRecibeForbidden(get("/api/v1/accesos/historial").session(sesion));
        assertNoRecibeForbidden(get("/api/v1/clientes/administracion").session(sesion));
        assertNoRecibeForbidden(get("/api/v1/clientes/administracion/CLI-0001").session(sesion));
        assertNoRecibeForbidden(get("/api/v1/tarjetas-rfid/modalidad").session(sesion));
        assertNoRecibeForbidden(get("/api/v1/tarjetas-rfid/personas?tipoEntidad=CLIENTE&busqueda=ab").session(sesion));
        assertNoRecibeForbidden(get("/api/v1/tarjetas-rfid?tipoEntidad=CLIENTE").session(sesion));
        assertNoRecibeForbidden(get("/api/v1/tarjetas-rfid/1").session(sesion));
        assertNoRecibeForbidden(post("/api/v1/tarjetas-rfid/1/cancelacion").session(sesion).with(csrf()));
        assertNoRecibeForbidden(get("/api/v1/rfid-1/estado-conexion").session(sesion));
        assertNoRecibeForbidden(post("/api/v1/rfid-1/capturas").session(sesion).with(csrf())
                .contentType(MediaType.APPLICATION_JSON).content("{}"));
        assertNoRecibeForbidden(get("/api/v1/rfid-1/capturas/activa").session(sesion));
        assertNoRecibeForbidden(get("/api/v1/rfid-1/capturas/" + CAPTURA_ID).session(sesion));
        assertNoRecibeForbidden(get("/api/v1/rfid-1/capturas/" + CAPTURA_ID + "/vista-previa").session(sesion));
        assertNoRecibeForbidden(post("/api/v1/rfid-1/capturas/" + CAPTURA_ID + "/confirmacion")
                .session(sesion).with(csrf()).contentType(MediaType.APPLICATION_JSON).content("{}"));
        assertNoRecibeForbidden(delete("/api/v1/rfid-1/capturas/" + CAPTURA_ID).session(sesion).with(csrf()));
        assertNoRecibeForbidden(get("/api/v1/eventos/administracion").session(sesion));
        assertNoRecibeForbidden(post("/api/v1/eventos/administracion/heartbeat").session(sesion).with(csrf())
                .contentType(MediaType.APPLICATION_JSON).content("{}"));

        mvc.perform(get("/api/v1/empleados").session(sesion))
                .andExpect(status().isForbidden());
        mvc.perform(get("/api/v1/empleados?soloElegiblesOperador=true").session(sesion))
                .andExpect(status().isForbidden());
        mvc.perform(get("/api/v1/operadores").session(sesion))
                .andExpect(status().isForbidden());
        mvc.perform(get("/api/v1/vision/fuentes/{id}/calibracion", UUID.randomUUID()).session(sesion))
                .andExpect(status().isForbidden());
        mvc.perform(post("/api/v1/transferencia/iniciar").session(sesion).with(csrf())
                        .contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isForbidden());
    }

    private void assertNoRecibeForbidden(MockHttpServletRequestBuilder solicitud) throws Exception {
        int estado = mvc.perform(solicitud).andReturn().getResponse().getStatus();
        assertNotEquals(403, estado, solicitud.toString());
    }

    private OperadorSesion crearSesionOperador() {
        PrincipalPropietario operador = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.OPERADOR, 1, 1, "operador@example.test");
        MockHttpSession sesion = new MockHttpSession();
        SecurityContext contexto = SecurityContextHolder.createEmptyContext();
        contexto.setAuthentication(UsernamePasswordAuthenticationToken.authenticated(
                operador, null, List.of(new SimpleGrantedAuthority("ROLE_OPERADOR"))));
        sesion.setAttribute(HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY, contexto);
        gestorSesiones.registrar(sesion, operador);
        return new OperadorSesion(operador, sesion);
    }

    private record OperadorSesion(PrincipalPropietario principal, MockHttpSession sesion) {
        UUID cuentaId() { return principal.cuentaId(); }
        long revisionAcceso() { return principal.revisionAcceso(); }
        long revisionPropietario() { return principal.revisionPropietario(); }
        RolCuenta rol() { return principal.rol(); }
    }
}
