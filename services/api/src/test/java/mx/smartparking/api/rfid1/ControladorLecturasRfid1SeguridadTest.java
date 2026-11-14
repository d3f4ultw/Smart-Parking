package mx.smartparking.api.rfid1;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import jakarta.servlet.http.Cookie;
import java.util.UUID;
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
class ControladorLecturasRfid1SeguridadTest extends ControladorLecturasRfid1TestSupport {

    @Test
    void lecturaValidaNoNecesitaSesionNiCsrfYNoExponeElUid() throws Exception {
        MvcResult resultado = mvc.perform(post(RUTA)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .header("Idempotency-Key", CLAVE_IDEMPOTENCIA)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(CUERPO_VALIDO))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.estado").value("RECIBIDA"))
                .andExpect(jsonPath("$.accion").value("NINGUNA"))
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store, private"))
                .andReturn();

        assertNull(resultado.getRequest().getSession(false));
        assertTrue(resultado.getResponse().getHeaders(HttpHeaders.SET_COOKIE).isEmpty());
        assertFalse(resultado.getResponse().getContentAsString().contains("04a1b2c3"));
    }

    @Test
    void admiteUidCanonicosDeCuatroSieteYDiezBytes() throws Exception {
        for (String uid : new String[] {
            "04A1B2C3", "04A1B2C3D4E5F6", "04A1B2C3D4E5F6071829"
        }) {
            MvcResult resultado = recibir(
                    "{\"secuencia\":42,\"uid\":\"" + uid + "\"}", UUID.randomUUID().toString());
            assertFalse(resultado.getResponse().getContentAsString().contains(uid));
        }
    }

    @Test
    void aceptaSecuenciasDeCeroHastaElMaximoDe16Bits() throws Exception {
        recibir("{\"secuencia\":0,\"uid\":\"04A1B2C3\"}", UUID.randomUUID().toString());
        recibir("{\"secuencia\":65535,\"uid\":\"04A1B2C3\"}", UUID.randomUUID().toString());
    }

    @Test
    void mismaClaveIdempotenteRepiteLaRespuestaSinEfectoDeNegocio() throws Exception {
        String primera = recibir(CUERPO_VALIDO, CLAVE_IDEMPOTENCIA).getResponse().getContentAsString();
        String repetida = recibir(CUERPO_VALIDO, CLAVE_IDEMPOTENCIA).getResponse().getContentAsString();

        assertEquals(primera, repetida);
        assertTrue(primera.contains("\"estado\":\"RECIBIDA\""));
        assertTrue(primera.contains("\"accion\":\"NINGUNA\""));
        assertFalse(primera.contains("04a1b2c3"));
    }

    @Test
    void tokenAusenteEIncorrectoRecibenElMismoErrorGenerico() throws Exception {
        String ausente = mvc.perform(post(RUTA)
                        .header("Idempotency-Key", CLAVE_IDEMPOTENCIA)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(CUERPO_VALIDO))
                .andExpect(status().isUnauthorized())
                .andReturn().getResponse().getContentAsString();
        String incorrecto = mvc.perform(post(RUTA)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN + "x")
                        .header("Idempotency-Key", CLAVE_IDEMPOTENCIA)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(CUERPO_VALIDO))
                .andExpect(status().isUnauthorized())
                .andReturn().getResponse().getContentAsString();

        assertEquals(ausente, incorrecto);
        assertFalse(ausente.contains(TOKEN));
        assertFalse(ausente.contains("04a1b2c3"));
    }

    @Test
    void noAceptaTokenEnCookieNiEnParametro() throws Exception {
        mvc.perform(post(RUTA + "?token=" + TOKEN)
                        .cookie(new Cookie("RFID1_TOKEN", TOKEN))
                        .header("Idempotency-Key", CLAVE_IDEMPOTENCIA)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(CUERPO_VALIDO))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void rutaYMetodoExactosLimitanLaAutenticacionDeDispositivo() throws Exception {
        mvc.perform(get(RUTA).header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN))
                .andExpect(status().isUnauthorized());
        mvc.perform(post(RUTA + "/extra")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .header("Idempotency-Key", CLAVE_IDEMPOTENCIA)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(CUERPO_VALIDO))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.codigo").value("CSRF_RECHAZADO"));
    }
}
