package mx.smartparking.api.rfid1;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import jakarta.servlet.http.Cookie;
import mx.smartparking.api.seguridad.rfid1.AutenticadorDispositivoRfid1;
import mx.smartparking.api.seguridad.rfid1.FiltroAutenticacionDispositivoRfid1;
import mx.smartparking.api.seguridad.FiltroSesionPropietario;
import mx.smartparking.api.seguridad.cliente.FiltroSesionCliente;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MvcResult;

/** Comprueba el contrato técnico y su separación de sesiones y CSRF de navegador. */
@SpringBootTest(properties = {
        "spring.profiles.active=test",
        "spring.application.name=rfid1-api-test",
        "server.address=127.0.0.1",
        "server.port=0",
        "spring.flyway.enabled=false",
        "spring.datasource.url=jdbc:postgresql://127.0.0.1:1/smartparking_test",
        "spring.datasource.username=test",
        "spring.datasource.password=test"
})
class CadenaSeguridadDispositivoRfid1Test extends ControladorLecturasRfid1TestSupport {

    @Test
    void endpointsDeCapturaExigenBearerYNoAceptanSesionWebComoCredencialDeDispositivo() throws Exception {
        mvc.perform(get(RUTA_CAPTURA_ACTIVA))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.codigo").value("DISPOSITIVO_NO_AUTORIZADO"));
        mvc.perform(post(RUTA_ESTADO_CAPTURA)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"estado\":\"ESCANEANDO\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.codigo").value("DISPOSITIVO_NO_AUTORIZADO"));

        mvc.perform(get(RUTA_CAPTURA_ACTIVA).header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN))
                .andExpect(status().isNoContent());
        mvc.perform(get("/api/v1/rfid-1/capturas/activa")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void cadenaStatelessCubreSoloLasRutasExactasDelDispositivo() {
        var cadena = cadenaSeguridad.getFilterChains().get(0);
        for (MockHttpServletRequest solicitud : new MockHttpServletRequest[] {
            new MockHttpServletRequest("GET", RUTA_CAPTURA_ACTIVA),
            new MockHttpServletRequest("POST", RUTA_ESTADO_CAPTURA)
        }) {
            solicitud.setServletPath(solicitud.getRequestURI());
            assertTrue(cadena.matches(solicitud));
            var filtros = cadena.getFilters();
            assertTrue(filtros.stream().anyMatch(FiltroAutenticacionDispositivoRfid1.class::isInstance));
            assertFalse(filtros.stream().anyMatch(FiltroSesionPropietario.class::isInstance));
            assertFalse(filtros.stream().anyMatch(FiltroSesionCliente.class::isInstance));
        }

        MockHttpServletRequest rutaExtendida = new MockHttpServletRequest("POST", RUTA_ESTADO_CAPTURA + "/extra");
        rutaExtendida.setServletPath(rutaExtendida.getRequestURI());
        assertFalse(cadena.matches(rutaExtendida));
    }

    @Test
    void bearerRfidNoAutorizaRutasWebNiOmiteCsrf() throws Exception {
        mvc.perform(get("/api/v1/panel").header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN))
                .andExpect(status().isUnauthorized());
        mvc.perform(get("/api/v1/clientes/portal").header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN))
                .andExpect(status().isUnauthorized());
        mvc.perform(post("/api/v1/empleados")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.codigo").value("CSRF_RECHAZADO"));
        mvc.perform(get("/api/v1/tarjetas-rfid/personas?tipoEntidad=CLIENTE&busqueda=ab")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN))
                .andExpect(status().isUnauthorized());
        mvc.perform(post("/api/v1/tarjetas-rfid/1/cancelacion")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.codigo").value("CSRF_RECHAZADO"))
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store, private"))
                .andExpect(header().string(HttpHeaders.VARY, "Cookie"));
        mvc.perform(get("/api/v1/rfid-1/capturas/00112233445566778899aabbccddeeff/vista-previa")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN))
                .andExpect(status().isUnauthorized());
        mvc.perform(post("/api/v1/rfid-1/capturas/00112233445566778899aabbccddeeff/confirmacion")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.codigo").value("CSRF_RECHAZADO"));
    }

    @Test
    void rechazaSecuenciaUidClaveYJsonInvalidos() throws Exception {
        rechazar("{\"secuencia\":-1,\"uid\":\"04A1B2C3\"}", CLAVE_IDEMPOTENCIA);
        rechazar("{\"secuencia\":65536,\"uid\":\"04A1B2C3\"}", CLAVE_IDEMPOTENCIA);
        rechazar("{\"secuencia\":9223372036854775808,\"uid\":\"04A1B2C3\"}", CLAVE_IDEMPOTENCIA);
        rechazar("{\"secuencia\":42.5,\"uid\":\"04A1B2C3\"}", CLAVE_IDEMPOTENCIA);
        rechazar("{\"secuencia\":42,\"uid\":\"04A1B2C\"}", CLAVE_IDEMPOTENCIA);
        rechazar("{\"secuencia\":42,\"uid\":\"04A1B2CG\"}", CLAVE_IDEMPOTENCIA);
        rechazar("{\"uid\":\"04A1B2C3\"}", CLAVE_IDEMPOTENCIA);
        rechazar(CUERPO_VALIDO, "no-es-uuid");
        rechazar(CUERPO_VALIDO, null);

        mvc.perform(post(RUTA)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .header("Idempotency-Key", CLAVE_IDEMPOTENCIA)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.codigo").value("LECTURA_NO_VALIDA"));
    }

    @Test
    void hashAusenteDeshabilitaElEndpointCon503() throws Exception {
        FiltroAutenticacionDispositivoRfid1 filtro = new FiltroAutenticacionDispositivoRfid1(
                new AutenticadorDispositivoRfid1(""));
        MockHttpServletRequest solicitud = new MockHttpServletRequest("POST", RUTA);
        MockHttpServletResponse respuesta = new MockHttpServletResponse();

        filtro.doFilter(solicitud, respuesta, (peticion, salida) -> {
            throw new AssertionError("Una credencial deshabilitada no debe continuar la cadena.");
        });

        assertEquals(503, respuesta.getStatus());
        assertTrue(respuesta.getContentAsString().contains("DISPOSITIVO_NO_DISPONIBLE"));
        assertFalse(respuesta.getContentAsString().contains(TOKEN));
    }

    @Test
    void primeraCadenaCoincideSoloConElPostExacto() {
        MockHttpServletRequest solicitud = new MockHttpServletRequest("POST", RUTA);
        solicitud.setServletPath(RUTA);
        var cadenas = cadenaSeguridad.getFilterChains();
        var filtrosPost = cadenas.get(0).getFilters();

        assertTrue(cadenas.get(0).matches(solicitud));
        assertTrue(filtrosPost.stream()
                .anyMatch(FiltroAutenticacionDispositivoRfid1.class::isInstance));
        assertFalse(filtrosPost.stream()
                .anyMatch(FiltroSesionPropietario.class::isInstance));
        assertFalse(filtrosPost.stream()
                .anyMatch(FiltroSesionCliente.class::isInstance));

        solicitud.setMethod("GET");
        assertFalse(cadenas.get(0).matches(solicitud));
    }

    @Test
    void mockMvcConstruyeLaRutaQueCoincideConLaCadenaDelDispositivo() throws Exception {
        MvcResult resultado = mvc.perform(post(RUTA)).andReturn();

        assertEquals(RUTA, resultado.getRequest().getRequestURI());
        assertTrue(cadenaSeguridad.getFilterChains().get(0).matches(resultado.getRequest()));
    }
}
