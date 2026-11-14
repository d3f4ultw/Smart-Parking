package mx.smartparking.api.vision;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.inOrder;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import jakarta.servlet.Filter;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import mx.smartparking.api.seguridad.cliente.GestorSesionesCliente;
import mx.smartparking.api.seguridad.cliente.PrincipalCliente;
import mx.smartparking.api.seguridad.vision.FiltroAutenticacionVision;
import mx.smartparking.api.vision.ContratosVision.RespuestaCalibracion;
import mx.smartparking.api.vision.ContratosVision.RespuestaFuente;
import mx.smartparking.api.vision.ContratosVision.RespuestaSesion;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.FilterChainProxy;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.security.web.csrf.CsrfTokenRepository;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;

/** Comprueba que Vision no comparte la sesión ni el Bearer de otros dispositivos. */
@SpringBootTest(properties = {
        "spring.profiles.active=test", "spring.application.name=vision-api-test", "spring.flyway.enabled=false",
        "server.address=127.0.0.1", "server.port=0",
        "spring.datasource.url=jdbc:postgresql://127.0.0.1:1/smartparking_test",
        "spring.datasource.username=test", "spring.datasource.password=test"
})
class SeguridadVisionTest {
    private static final String RUTA = "/api/v1/dispositivos/vision/sesiones";
    private static final String TOKEN = "token-sintetico-solo-para-prueba-vision";
    private static final String TOKEN_RFID = "token-sintetico-solo-para-prueba-rfid";
    private static final UUID FUENTE = UUID.fromString("22222222-2222-4222-8222-222222222222");
    private static final UUID SESION = UUID.fromString("33333333-3333-4333-8333-333333333333");
    private static final String CUERPO = "{\"fuenteId\":\"" + FUENTE
            + "\",\"solicitudId\":\"44444444-4444-4444-8444-444444444444\","
            + "\"iniciadaEn\":\"2026-11-02T00:00:00Z\"}";

    @Autowired private WebApplicationContext contexto;
    @Autowired private FilterChainProxy cadena;
    @Autowired private GestorSesionesPropietario sesionesPropietario;
    @Autowired private GestorSesionesCliente sesionesCliente;
    @Autowired private CsrfTokenRepository repositorioCsrf;
    @MockitoBean private ServicioVision servicio;
    @MockitoBean private ServicioEventosAdministracion eventos;
    @MockitoBean private RepositorioCuentas cuentas;
    private MockMvc mvc;

    @DynamicPropertySource
    static void configurar(DynamicPropertyRegistry propiedades) {
        propiedades.add("smartparking.vision.token-sha256", () -> sha256(TOKEN));
        propiedades.add("smartparking.vision.fuente-id", FUENTE::toString);
        propiedades.add("smartparking.rfid1.token-sha256", () -> sha256(TOKEN_RFID));
    }

    @BeforeEach
    void preparar() {
        mvc = MockMvcBuilders.webAppContextSetup(contexto).addFilters((Filter) cadena).build();
        when(servicio.abrirSesion(any())).thenReturn(new RespuestaSesion(SESION));
        when(servicio.consultarCajonesConVigencia()).thenReturn(new ServicioVision.LecturaCajones(List.of(), null));
        when(eventos.cursorActual()).thenReturn("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:1");
    }

    @Test
    void bearerAutorizadoNoCreaSesionNiNecesitaCsrf() throws Exception {
        MvcResult resultado = mvc.perform(post(RUTA).header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON).content(CUERPO))
                .andExpect(status().isOk()).andExpect(jsonPath("$.sesionId").value(SESION.toString())).andReturn();
        assertNull(resultado.getRequest().getSession(false));
        assertTrue(resultado.getResponse().getHeaders(HttpHeaders.SET_COOKIE).isEmpty());
    }

    @Test
    void tokenNoAutorizaOtraFuenteNiSeIntercambiaConRfid() throws Exception {
        mvc.perform(post(RUTA).header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON).content(CUERPO.replace(FUENTE.toString(),
                                "99999999-9999-4999-8999-999999999999")))
                .andExpect(status().isForbidden());
        mvc.perform(post(RUTA).header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN_RFID)
                        .contentType(MediaType.APPLICATION_JSON).content(CUERPO))
                .andExpect(status().isUnauthorized());
        mvc.perform(post("/api/v1/dispositivos/rfid-1/lecturas")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void rechazaNumerosDecimalesYJsonMalformado() throws Exception {
        String observacion = "{\"fuenteId\":\"" + FUENTE + "\",\"sesionId\":\"" + SESION
                + "\",\"solicitudId\":\"44444444-4444-4444-8444-444444444444\","
                + "\"secuencia\":1.5,\"revisionCalibracion\":1,\"hashCalibracion\":\""
                + "a".repeat(64) + "\",\"observadoEn\":\"2026-11-02T00:00:00Z\","
                + "\"zonas\":[{\"visionZoneId\":\"55555555-5555-4555-8555-555555555555\","
                + "\"estado\":\"LIBRE\"}]}";
        String ruta = "/api/v1/dispositivos/vision/observaciones";
        mvc.perform(post(ruta).header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON).content(observacion))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.codigo").value("VISION_INVALIDA"));
        mvc.perform(post(ruta).header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON).content("{"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.codigo").value("VISION_INVALIDA"));
    }

    @Test
    void bearerNoAutorizaAdministracionYCsrfHumanoSeConserva() throws Exception {
        mvc.perform(get("/api/v1/vision/cajones").header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN))
                .andExpect(status().isUnauthorized());
        mvc.perform(get("/api/v1/empleados").header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN))
                .andExpect(status().isUnauthorized());
        mvc.perform(post("/api/v1/vision/fuentes").header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.codigo").value("CSRF_RECHAZADO"));
    }

    @Test
    void operadorYClienteConSesionVigenteNoPuedenLeerNiAdministrarVision() throws Exception {
        MockHttpSession operador = sesionPropietario(RolCuenta.OPERADOR);
        MockHttpSession cliente = sesionCliente();
        CsrfToken csrfOperador = crearCsrf(operador);
        CsrfToken csrfCliente = crearCsrf(cliente);
        when(servicio.consultarCajonesConVigencia())
                .thenReturn(new ServicioVision.LecturaCajones(List.of(), null));

        mvc.perform(get("/api/v1/vision/cajones").session(operador))
                .andExpect(status().isOk());
        mvc.perform(get("/api/v1/vision/cajones").session(cliente))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.codigo").value("PERMISO_INSUFICIENTE"));
        mvc.perform(get("/api/v1/vision/fuentes/" + FUENTE + "/calibracion").session(operador))
                .andExpect(status().isForbidden());
        mvc.perform(get("/api/v1/vision/fuentes/" + FUENTE + "/calibracion").session(operador)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN))
                .andExpect(status().isForbidden());
        mvc.perform(put("/api/v1/vision/fuentes/" + FUENTE + "/calibracion").session(operador)
                        .header(csrfOperador.getHeaderName(), csrfOperador.getToken())
                        .contentType(MediaType.APPLICATION_JSON).content(cuerpoCalibracion()))
                .andExpect(status().isForbidden());
        verify(servicio, never()).consultarCalibracion(FUENTE);
        verify(servicio, never()).activarCalibracion(org.mockito.ArgumentMatchers.eq(FUENTE), any());

        for (MockHttpSession sesion : List.of(operador, cliente)) {
            CsrfToken tokenCsrf = sesion == operador ? csrfOperador : csrfCliente;
            mvc.perform(post("/api/v1/vision/fuentes").session(sesion)
                            .header(tokenCsrf.getHeaderName(), tokenCsrf.getToken())
                            .contentType(MediaType.APPLICATION_JSON).content(cuerpoFuente()))
                    .andExpect(status().isForbidden())
                    .andExpect(jsonPath("$.codigo").value("PERMISO_INSUFICIENTE"));
        }
        mvc.perform(get("/api/v1/vision/fuentes/" + FUENTE + "/calibracion").session(cliente))
                .andExpect(status().isUnauthorized());
        mvc.perform(put("/api/v1/vision/fuentes/" + FUENTE + "/calibracion").session(cliente)
                        .header(csrfCliente.getHeaderName(), csrfCliente.getToken())
                        .contentType(MediaType.APPLICATION_JSON).content(cuerpoCalibracion()))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void duenoConSesionYCsrfVigentesAlcanzaConsultasYAdministracion() throws Exception {
        MockHttpSession sesion = sesionPropietario(RolCuenta.DUENO);
        CsrfToken tokenCsrf = crearCsrf(sesion);
        when(servicio.registrarFuente(any())).thenReturn(new RespuestaFuente(FUENTE));
        mvc.perform(get("/api/v1/vision/cajones").session(sesion)).andExpect(status().isOk())
                .andExpect(header().string("X-Eventos-Cursor", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:1"))
                .andExpect(header().doesNotExist("X-Vision-Vigencia-Restante-Ms"));
        mvc.perform(get("/api/v1/vision/fuentes/" + FUENTE + "/calibracion").session(sesion))
                .andExpect(status().isUnauthorized());
        mvc.perform(post("/api/v1/vision/fuentes").session(sesion)
                        .header(tokenCsrf.getHeaderName(), tokenCsrf.getToken())
                        .contentType(MediaType.APPLICATION_JSON).content(cuerpoFuente()))
                .andExpect(status().isOk()).andExpect(jsonPath("$.fuenteId").value(FUENTE.toString()));
        verify(servicio).consultarCajonesConVigencia();
        var orden = inOrder(eventos, servicio);
        orden.verify(eventos).cursorActual();
        orden.verify(servicio).consultarCajonesConVigencia();
        verify(servicio).registrarFuente(any());
    }

    @Test
    void lecturaConVigenciaConservaArrayYEntregaLosDosEncabezados() throws Exception {
        MockHttpSession sesion = sesionPropietario(RolCuenta.DUENO);
        when(servicio.consultarCajonesConVigencia()).thenReturn(new ServicioVision.LecturaCajones(
                List.of(new ContratosVision.EstadoCajon(UUID.randomUUID(), "C1", "LIBRE", "LIBRE", null,
                        "Entrada principal")),
                12_345L));
        mvc.perform(get("/api/v1/vision/cajones").session(sesion))
                .andExpect(status().isOk())
                .andExpect(header().string("X-Eventos-Cursor", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:1"))
                .andExpect(header().string("X-Vision-Vigencia-Restante-Ms", "12345"))
                .andExpect(jsonPath("$[0].estado").value("LIBRE"))
                .andExpect(jsonPath("$[0].displayName").value("Entrada principal"));
    }

    @Test
    void nombreDeCajonExigeSesionAutorizadaYCsrfSinAceptarBearer() throws Exception {
        UUID cajonId = UUID.randomUUID();
        String ruta = "/api/v1/vision/cajones/" + cajonId + "/display-name";
        String cuerpo = "{\"displayName\":\"Entrada principal\"}";
        MockHttpSession dueno = sesionPropietario(RolCuenta.DUENO);
        CsrfToken csrfDueno = crearCsrf(dueno);
        mvc.perform(put(ruta).session(dueno).contentType(MediaType.APPLICATION_JSON).content(cuerpo))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.codigo").value("CSRF_RECHAZADO"));
        MockHttpSession operador = sesionPropietario(RolCuenta.OPERADOR);
        CsrfToken csrfOperador = crearCsrf(operador);
        mvc.perform(put(ruta).session(operador).header(csrfOperador.getHeaderName(), csrfOperador.getToken())
                        .contentType(MediaType.APPLICATION_JSON).content(cuerpo))
                .andExpect(status().isNoContent());
        MockHttpSession cliente = sesionCliente();
        CsrfToken csrfCliente = crearCsrf(cliente);
        mvc.perform(put(ruta).session(cliente).header(csrfCliente.getHeaderName(), csrfCliente.getToken())
                        .contentType(MediaType.APPLICATION_JSON).content(cuerpo))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.codigo").value("PERMISO_INSUFICIENTE"));
        MockHttpSession anonima = new MockHttpSession();
        CsrfToken csrfAnonimo = crearCsrf(anonima);
        mvc.perform(put(ruta).session(anonima).header(csrfAnonimo.getHeaderName(), csrfAnonimo.getToken())
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON).content(cuerpo))
                .andExpect(status().isUnauthorized());
        mvc.perform(put(ruta).session(dueno).header(csrfDueno.getHeaderName(), csrfDueno.getToken())
                        .contentType(MediaType.APPLICATION_JSON).content(cuerpo))
                .andExpect(status().isNoContent())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store, private"));
        verify(servicio, org.mockito.Mockito.times(2)).actualizarNombreCajon(cajonId, "Entrada principal");
        mvc.perform(put(ruta).session(dueno).header(csrfDueno.getHeaderName(), csrfDueno.getToken())
                        .contentType(MediaType.APPLICATION_JSON).content("{\"displayName\":null}"))
                .andExpect(status().isNoContent());
        verify(servicio).actualizarNombreCajon(cajonId, null);
        mvc.perform(put(ruta).session(dueno).header(csrfDueno.getHeaderName(), csrfDueno.getToken())
                        .contentType(MediaType.APPLICATION_JSON).content("{"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void laCadenaSoloReconoceLasDosRutasYElMetodoExactos() {
        var vision = cadena.getFilterChains().get(1);
        for (String ruta : new String[] {RUTA, "/api/v1/dispositivos/vision/observaciones"}) {
            MockHttpServletRequest post = new MockHttpServletRequest("POST", ruta);
            post.setServletPath(ruta);
            assertTrue(vision.matches(post));
            post.setMethod("GET");
            assertFalse(vision.matches(post));
        }
        MockHttpServletRequest extra = new MockHttpServletRequest("POST", RUTA + "/extra");
        extra.setServletPath(extra.getRequestURI());
        assertFalse(vision.matches(extra));
        String rutaCalibracion = "/api/v1/vision/fuentes/" + FUENTE + "/calibracion";
        MockHttpServletRequest consulta = new MockHttpServletRequest("GET", rutaCalibracion);
        consulta.setServletPath(rutaCalibracion);
        assertTrue(vision.matches(consulta));
        consulta.setSession(sesionPropietario(RolCuenta.OPERADOR));
        assertFalse(vision.matches(consulta));
        consulta.setMethod("PUT");
        assertFalse(vision.matches(consulta));
        consulta.setSession(null);
        assertTrue(vision.matches(consulta));
        consulta.setMethod("POST");
        assertFalse(vision.matches(consulta));
        MockHttpServletRequest extraCalibracion = new MockHttpServletRequest("GET", rutaCalibracion + "/extra");
        extraCalibracion.setServletPath(rutaCalibracion + "/extra");
        assertFalse(vision.matches(extraCalibracion));
    }

    @Test
    void bearerVisionConsultaYActualizaSoloSuFuenteSinSesion() throws Exception {
        String ruta = "/api/v1/vision/fuentes/" + FUENTE + "/calibracion";
        String otraRuta = "/api/v1/vision/fuentes/99999999-9999-4999-8999-999999999999/calibracion";
        UUID zonaId = UUID.fromString("55555555-5555-4555-8555-555555555555");
        RespuestaCalibracion calibracion = new RespuestaCalibracion(FUENTE,
                List.of(new ContratosVision.ZonaConfiguracion(zonaId, "C1", UUID.randomUUID())));
        when(servicio.consultarCalibracion(FUENTE)).thenReturn(calibracion);
        when(servicio.activarCalibracion(org.mockito.ArgumentMatchers.eq(FUENTE), any()))
                .thenReturn(calibracion);

        MvcResult consulta = mvc.perform(get(ruta).header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store, private"))
                .andExpect(jsonPath("$.fuenteId").value(FUENTE.toString()))
                .andExpect(jsonPath("$.zonas[0].visionZoneId").value(zonaId.toString())).andReturn();
        assertNull(consulta.getRequest().getSession(false));
        assertTrue(consulta.getResponse().getHeaders(HttpHeaders.SET_COOKIE).isEmpty());

        MvcResult guardado = mvc.perform(put(ruta).header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON).content(cuerpoCalibracion()))
                .andExpect(status().isNoContent())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store, private")).andReturn();
        assertNull(guardado.getRequest().getSession(false));
        assertTrue(guardado.getResponse().getHeaders(HttpHeaders.SET_COOKIE).isEmpty());

        mvc.perform(get(otraRuta).header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN))
                .andExpect(status().isForbidden());
        mvc.perform(put(otraRuta).header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON).content(cuerpoCalibracion()))
                .andExpect(status().isForbidden());
        verify(servicio).consultarCalibracion(FUENTE);
        verify(servicio).activarCalibracion(org.mockito.ArgumentMatchers.eq(FUENTE), any());
    }

    @Test
    void publicadorPythonActualSiguePublicandoConCamposLegacy() throws Exception {
        when(servicio.observar(any())).thenReturn(new ContratosVision.RespuestaObservacion(true));
        mvc.perform(post(RUTA).header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON).content(CUERPO))
                .andExpect(status().isOk()).andExpect(jsonPath("$.sesionId").value(SESION.toString()));

        String observacion = "{\"fuenteId\":\"" + FUENTE + "\",\"sesionId\":\"" + SESION
                + "\",\"secuencia\":1,\"solicitudId\":\"66666666-6666-4666-8666-666666666666\","
                + "\"revisionCalibracion\":7,\"hashCalibracion\":\"" + "a".repeat(64)
                + "\",\"observadoEn\":\"2026-11-04T23:00:00Z\",\"zonas\":[{\"visionZoneId\":\""
                + "55555555-5555-4555-8555-555555555555\",\"estado\":\"OCUPADO\"}]}";
        mvc.perform(post("/api/v1/dispositivos/vision/observaciones")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON).content(observacion))
                .andExpect(status().isOk()).andExpect(jsonPath("$.aceptada").value(true));
        verify(servicio).observar(any());
    }

    @Test
    void faltaDeHashOFuenteDeshabilitaSinRevelarElToken() throws Exception {
        for (FiltroAutenticacionVision filtro : new FiltroAutenticacionVision[] {
                new FiltroAutenticacionVision("", FUENTE.toString(), ""),
                new FiltroAutenticacionVision(sha256(TOKEN), "", ""),
                new FiltroAutenticacionVision(sha256(TOKEN), FUENTE.toString(), sha256(TOKEN))}) {
            MockHttpServletResponse respuesta = new MockHttpServletResponse();
            filtro.doFilter(new MockHttpServletRequest("POST", RUTA), respuesta,
                    (peticion, salida) -> { throw new AssertionError("No debe continuar."); });
            assertEquals(503, respuesta.getStatus());
            assertFalse(respuesta.getContentAsString().contains(TOKEN));
        }
    }

    private static String sha256(String texto) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(texto.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception excepcion) {
            throw new IllegalStateException(excepcion);
        }
    }

    private MockHttpSession sesionPropietario(RolCuenta rol) {
        PrincipalPropietario principal = new PrincipalPropietario(
                UUID.randomUUID(), rol, 1, 1, "prueba@example.invalid");
        MockHttpSession sesion = sesionConPrincipal(principal, "ROLE_" + rol.name());
        sesionesPropietario.registrar(sesion, principal);
        when(cuentas.sesionVigente(principal.cuentaId(), 1, rol.name(), 1)).thenReturn(true);
        return sesion;
    }

    private MockHttpSession sesionCliente() {
        PrincipalCliente principal = new PrincipalCliente(UUID.randomUUID(), 1, "cliente@example.invalid");
        MockHttpSession sesion = sesionConPrincipal(principal, "ROLE_CLIENTE");
        sesionesCliente.registrar(sesion, principal);
        when(cuentas.sesionVigente(principal.cuentaId(), 1, "CLIENTE", 0)).thenReturn(true);
        return sesion;
    }

    private static MockHttpSession sesionConPrincipal(Object principal, String autoridad) {
        MockHttpSession sesion = new MockHttpSession();
        SecurityContext contexto = SecurityContextHolder.createEmptyContext();
        contexto.setAuthentication(UsernamePasswordAuthenticationToken.authenticated(
                principal, null, List.of(new SimpleGrantedAuthority(autoridad))));
        sesion.setAttribute(HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY, contexto);
        return sesion;
    }

    private CsrfToken crearCsrf(MockHttpSession sesion) {
        MockHttpServletRequest solicitud = new MockHttpServletRequest();
        solicitud.setSession(sesion);
        CsrfToken token = repositorioCsrf.generateToken(solicitud);
        repositorioCsrf.saveToken(token, solicitud, new MockHttpServletResponse());
        return token;
    }

    private static String cuerpoFuente() {
        return "{\"fuenteId\":\"" + FUENTE + "\"}";
    }

    private static String cuerpoCalibracion() {
        return "{\"zonas\":[{\"visionZoneId\":\"55555555-5555-4555-8555-555555555555\","
                + "\"etiqueta\":\"C1\",\"cajonId\":null}]}";
    }
}
