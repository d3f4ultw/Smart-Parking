package mx.smartparking.api.rfid3.controlador;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import mx.smartparking.api.rfid3.persistencia.LecturaRfid3ConflictException;
import mx.smartparking.api.rfid3.persistencia.RepositorioRfid3;
import mx.smartparking.api.rfid3.persistencia.ResultadoSalidaRfid3;
import mx.smartparking.api.rfid3.servicio.ServicioRfid3;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.TransactionSystemException;

class ControladorSalidasRfid3Test {

    private static final String RUTA = "/api/v1/dispositivos/rfid-3/salidas";
    private static final String CUERPO = "{\"uid\":\"abcdef12\","
            + "\"lecturaId\":\"550e8400-e29b-41d4-a716-446655440000\"}";
    private RepositorioRfid3 repositorio;
    private MockMvc mvc;

    @BeforeEach
    void preparar() {
        repositorio = mock(RepositorioRfid3.class);
        mvc = MockMvcBuilders.standaloneSetup(new ControladorSalidasRfid3(new ServicioRfid3(repositorio)))
                .setControllerAdvice(new ManejadorErroresDispositivoRfid3()).build();
    }

    @Test
    void autorizacionConfirmadaNoIncluyeMotivoYEsPrivada() throws Exception {
        when(repositorio.registrarSalida(any(), any())).thenReturn(ResultadoSalidaRfid3.autorizada());
        mvc.perform(post(RUTA).contentType(MediaType.APPLICATION_JSON).content(CUERPO))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.resultado").value("AUTORIZADA"))
                .andExpect(jsonPath("$.motivo").doesNotExist())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store, private"))
                .andExpect(header().string(HttpHeaders.VARY, "Authorization"));
    }

    @Test
    void exponeLosTresMotivosDeDenegacion() throws Exception {
        for (String motivo : new String[] {"TARJETA_DESCONOCIDA", "TARJETA_CANCELADA", "SIN_ENTRADA_ABIERTA"}) {
            when(repositorio.registrarSalida(any(), any())).thenReturn(ResultadoSalidaRfid3.denegada(motivo));
            mvc.perform(post(RUTA).contentType(MediaType.APPLICATION_JSON).content(CUERPO))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.resultado").value("DENEGADA"))
                    .andExpect(jsonPath("$.motivo").value(motivo));
        }
    }

    @Test
    void rechazaJsonMalformadoCamposAusentesYTiposIncorrectos() throws Exception {
        for (String cuerpo : new String[] {"{", "{}", "null", "{\"uid\":12345678,"
                + "\"lecturaId\":\"550e8400-e29b-41d4-a716-446655440000\"}"}) {
            mvc.perform(post(RUTA).contentType(MediaType.APPLICATION_JSON).content(cuerpo))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.codigo").value("LECTURA_NO_VALIDA"))
                    .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store, private"));
        }
    }

    @Test
    void conflictoYErroresTransaccionalesNoSonAutorizacion() throws Exception {
        when(repositorio.registrarSalida(any(), any())).thenThrow(new LecturaRfid3ConflictException());
        mvc.perform(post(RUTA).contentType(MediaType.APPLICATION_JSON).content(CUERPO))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.codigo").value("LECTURA_EN_CONFLICTO"));

        doThrow(new DataAccessResourceFailureException("prueba")).when(repositorio).registrarSalida(any(), any());
        mvc.perform(post(RUTA).contentType(MediaType.APPLICATION_JSON).content(CUERPO))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.resultado").doesNotExist());

        doThrow(new TransactionSystemException("prueba")).when(repositorio).registrarSalida(any(), any());
        mvc.perform(post(RUTA).contentType(MediaType.APPLICATION_JSON).content(CUERPO))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.resultado").doesNotExist());
    }

    @Test
    void respuestaNoReconocidaFallaCerrada() throws Exception {
        when(repositorio.registrarSalida(any(), any())).thenReturn(new ResultadoSalidaRfid3("AUTORIZADA", "extra"));
        mvc.perform(post(RUTA).contentType(MediaType.APPLICATION_JSON).content(CUERPO))
                .andExpect(status().isServiceUnavailable());
    }
}
