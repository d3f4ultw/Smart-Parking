package mx.smartparking.api.rfid1;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import jakarta.servlet.Filter;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Base64;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.rfid1.servicio.ServicioEstadoConexionRfid1;
import mx.smartparking.api.rfid1.servicio.ServicioRfid1;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.FilterChainProxy;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;

/** Comprueba autenticación, privacidad y respuesta de los endpoints de estado RFID 1. */
@SpringBootTest(properties = {
        "spring.profiles.active=test",
        "spring.application.name=rfid1-estado-test",
        "server.address=127.0.0.1",
        "server.port=0",
        "spring.flyway.enabled=false",
        "spring.datasource.url=jdbc:postgresql://127.0.0.1:1/smartparking_test",
        "spring.datasource.username=test",
        "spring.datasource.password=test"
})
class ControladorEstadoConexionRfid1SeguridadTest {

    private static final String RUTA_DISPOSITIVO = "/api/v1/dispositivos/rfid-1/estado";
    private static final String RUTA_DUENO = "/api/v1/rfid-1/estado-conexion";
    private static final String TOKEN = Base64.getUrlEncoder().withoutPadding().encodeToString(new byte[32]);
    private static final String TOKEN_SHA256 = sha256(TOKEN);

    private MockMvc mvc;

    @Autowired
    private WebApplicationContext contextoWeb;

    @Autowired
    private FilterChainProxy cadenaSeguridad;

    @Autowired
    private GestorSesionesPropietario gestorSesiones;

    @Autowired
    private ServicioEstadoConexionRfid1 servicioEstado;

    @MockitoBean
    private RepositorioCuentas cuentas;

    @MockitoBean
    private ServicioRfid1 servicioRfid1;

    @DynamicPropertySource
    static void propiedadesDispositivo(DynamicPropertyRegistry registro) {
        registro.add("smartparking.rfid1.token-sha256", () -> TOKEN_SHA256);
    }

    @BeforeEach
    void prepararMockMvc() {
        mvc = MockMvcBuilders.webAppContextSetup(contextoWeb)
                .addFilters((Filter) cadenaSeguridad)
                .build();
    }

    @Test
    void heartbeatValidoSoloUsaBearerYDevuelveSinContenido() throws Exception {
        MvcResult resultado = mvc.perform(post(RUTA_DISPOSITIVO)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"conectado\":true}"))
                .andExpect(status().isNoContent())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store, private"))
                .andExpect(header().string(HttpHeaders.VARY, HttpHeaders.AUTHORIZATION))
                .andReturn();

        assertNull(resultado.getRequest().getSession(false));
        assertTrue(resultado.getResponse().getHeaders(HttpHeaders.SET_COOKIE).isEmpty());
        assertTrue(resultado.getResponse().getContentAsString().isEmpty());

        mvc.perform(post(RUTA_DISPOSITIVO)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"conectado\":false}"))
                .andExpect(status().isNoContent());
    }

    @Test
    void heartbeatRequiereBearerValidoYValorBooleano() throws Exception {
        mvc.perform(post(RUTA_DISPOSITIVO)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"conectado\":true}"))
                .andExpect(status().isUnauthorized());
        mvc.perform(post(RUTA_DISPOSITIVO)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer credencial-incorrecta")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"conectado\":true}"))
                .andExpect(status().isUnauthorized());
        mvc.perform(post(RUTA_DISPOSITIVO)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"conectado\":null}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void bearerDelDispositivoNoAutorizaLaConsultaDelDueno() throws Exception {
        mvc.perform(get(RUTA_DUENO).header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN))
                .andExpect(status().isUnauthorized());
        mvc.perform(get(RUTA_DUENO))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void consultaDuenoDevuelveSoloEstadoYEsPrivada() throws Exception {
        PrincipalPropietario dueno = nuevoPropietario(RolCuenta.DUENO);
        MockHttpSession sesion = sesionAutenticada(dueno);
        when(cuentas.sesionVigente(dueno.cuentaId(), dueno.revisionAcceso(),
                dueno.rol().name(), dueno.revisionPropietario())).thenReturn(true);
        servicioEstado.registrar(true);

        MvcResult resultado = mvc.perform(get(RUTA_DUENO).session(sesion))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.estado").value("CONECTADO"))
                .andExpect(jsonPath("$.actualizadoEn").isNotEmpty())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store, private"))
                .andExpect(header().string(HttpHeaders.VARY, HttpHeaders.COOKIE))
                .andReturn();

        String cuerpo = resultado.getResponse().getContentAsString().toLowerCase(java.util.Locale.ROOT);
        assertFalse(cuerpo.contains("uid"));
        assertFalse(cuerpo.contains(TOKEN.toLowerCase(java.util.Locale.ROOT)));
    }

    @Test
    void consultaEstadoPermiteOperadorConRespuestaPrivada() throws Exception {
        PrincipalPropietario operador = nuevoPropietario(RolCuenta.OPERADOR);
        MockHttpSession sesion = sesionAutenticada(operador);
        when(cuentas.sesionVigente(operador.cuentaId(), operador.revisionAcceso(),
                operador.rol().name(), operador.revisionPropietario())).thenReturn(true);
        servicioEstado.registrar(false);

        mvc.perform(get(RUTA_DUENO).session(sesion))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.estado").value("DESCONECTADO"))
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store, private"));
    }

    private PrincipalPropietario nuevoPropietario(RolCuenta rol) {
        return new PrincipalPropietario(UUID.randomUUID(), rol, 1, 1, "persona@test.invalid");
    }

    private MockHttpSession sesionAutenticada(PrincipalPropietario propietario) {
        MockHttpSession sesion = new MockHttpSession();
        SecurityContext contexto = SecurityContextHolder.createEmptyContext();
        contexto.setAuthentication(UsernamePasswordAuthenticationToken.authenticated(
                propietario, null, List.of(new SimpleGrantedAuthority("ROLE_" + propietario.rol().name()))));
        sesion.setAttribute(HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY, contexto);
        gestorSesiones.registrar(sesion, propietario);
        return sesion;
    }

    private static String sha256(String texto) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(texto.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException excepcion) {
            throw new ExceptionInInitializerError(excepcion);
        }
    }
}
