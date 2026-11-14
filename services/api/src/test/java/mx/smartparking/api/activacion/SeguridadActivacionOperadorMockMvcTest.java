package mx.smartparking.api.activacion;

import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.ConfiguracionSeguridadPropietario;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.ProveedorAutenticacionPropietario;
import mx.smartparking.api.seguridad.cliente.ProveedorAutenticacionCliente;
import mx.smartparking.api.seguridad.cliente.GestorSesionesCliente;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

/** Verifica CSRF y encabezados de las rutas públicas de activación. */
@WebMvcTest(controllers = ControladorActivacionOperador.class,
        properties = {
                "spring.profiles.active=test",
                "spring.application.name=activacion-operador-csrf-test",
                "server.address=127.0.0.1",
                "server.port=0"
        })
@Import({ConfiguracionSeguridadPropietario.class, FiltroEncabezadosActivacionOperador.class})
class SeguridadActivacionOperadorMockMvcTest {

    @Autowired
    private MockMvc mvc;

    @MockitoBean
    private ServicioActivacionOperador servicio;

    @MockitoBean
    private ServicioAdministracionInvitacionesOperador administracionInvitaciones;

    @MockitoBean
    private ProveedorAutenticacionPropietario proveedorAutenticacion;

    @MockitoBean
    private ProveedorAutenticacionCliente proveedorAutenticacionCliente;

    @MockitoBean
    private GestorSesionesCliente gestorSesionesCliente;

    @MockitoBean
    private GestorSesionesPropietario gestorSesiones;

    @MockitoBean
    private RepositorioCuentas repositorioCuentas;

    @Test
    void ambosPostPublicosRechazanSolicitudSinCsrf() throws Exception {
        mvc.perform(post("/api/v1/operadores/activacion/validar")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"token\":\"token-no-valido\"}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.codigo").value("CSRF_RECHAZADO"))
                .andExpect(header().string("Cache-Control", org.hamcrest.Matchers.containsString("no-store")))
                .andExpect(header().string("Referrer-Policy", "no-referrer"));

        mvc.perform(post("/api/v1/operadores/activacion/completar")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"token\":\"token-no-valido\",\"contrasena\":\"secreta\"}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.codigo").value("CSRF_RECHAZADO"))
                .andExpect(header().string("Cache-Control", org.hamcrest.Matchers.containsString("no-store")))
                .andExpect(header().string("Referrer-Policy", "no-referrer"));

        verifyNoInteractions(servicio);
    }

    @Test
    void postPublicoConCsrfTambienConservaEncabezadosPrivados() throws Exception {
        org.mockito.Mockito.when(servicio.validar("token-no-valido"))
                .thenReturn(new RespuestaValidacionActivacionOperador(false));

        mvc.perform(post("/api/v1/operadores/activacion/validar")
                        .with(csrf())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"token\":\"token-no-valido\"}"))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", org.hamcrest.Matchers.containsString("no-store")))
                .andExpect(header().string("Referrer-Policy", "no-referrer"));
    }
}
