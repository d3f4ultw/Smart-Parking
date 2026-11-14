package mx.smartparking.api.rfid1;

import static org.mockito.Mockito.when;
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
import java.util.Optional;
import mx.smartparking.api.rfid1.servicio.ServicioRfid1;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.security.web.FilterChainProxy;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;

/** Fixture compartido por las suites de ControladorLecturasRfid1SeguridadTest. */
abstract class ControladorLecturasRfid1TestSupport {
     static final String RUTA = "/api/v1/dispositivos/rfid-1/lecturas";
     static final String RUTA_CAPTURA_ACTIVA = "/api/v1/dispositivos/rfid-1/capturas/activa";
     static final String RUTA_ESTADO_CAPTURA =
            "/api/v1/dispositivos/rfid-1/capturas/00112233445566778899aabbccddeeff/estado";
     static final String TOKEN = Base64.getUrlEncoder().withoutPadding().encodeToString(new byte[32]);
     static final String TOKEN_SHA256 = sha256(TOKEN);
     static final String CLAVE_IDEMPOTENCIA = "8efc69c1-c167-4e2e-a9d5-74fd1edbd191";
     static final String CUERPO_VALIDO = "{\"secuencia\":42,\"uid\":\"04a1b2c3\"}";

     MockMvc mvc;

    @Autowired
     WebApplicationContext contextoWeb;

    @Autowired
     FilterChainProxy cadenaSeguridad;

    @MockitoBean
     RepositorioCuentas cuentas;

    @MockitoBean
     ServicioRfid1 servicioRfid1;

    @DynamicPropertySource
    static void propiedadesDispositivo(DynamicPropertyRegistry registro) {
        registro.add("smartparking.rfid1.token-sha256", () -> TOKEN_SHA256);
    }

    @BeforeEach
    void prepararMockMvc() {
        when(servicioRfid1.consultarCapturaActivaDispositivo()).thenReturn(Optional.empty());
        mvc = MockMvcBuilders.webAppContextSetup(contextoWeb)
                .addFilters((Filter) cadenaSeguridad)
                .build();
    }



     MvcResult recibir(String cuerpo, String clave) throws Exception {
        return mvc.perform(post(RUTA)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .header("Idempotency-Key", clave)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(cuerpo))
                .andExpect(status().isAccepted())
                .andReturn();
    }

     void rechazar(String cuerpo, String clave) throws Exception {
        mvc.perform(post(RUTA)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TOKEN)
                        .header("Idempotency-Key", clave)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(cuerpo))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.codigo").value("LECTURA_NO_VALIDA"));
    }

     static String sha256(String texto) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(texto.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException excepcion) {
            throw new ExceptionInInitializerError(excepcion);
        }
    }
}
