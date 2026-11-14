package mx.smartparking.api.clientes.administracion.controlador;

import static org.hamcrest.Matchers.nullValue;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;
import java.util.UUID;
import mx.smartparking.api.clientes.administracion.modelo.ClienteResumenAdministracion;
import mx.smartparking.api.clientes.administracion.modelo.DetalleClienteAdministracion;
import mx.smartparking.api.clientes.administracion.modelo.PaginaClientesAdministracion;
import mx.smartparking.api.clientes.administracion.servicio.ServicioAdministracionClientes;
import mx.smartparking.api.clientes.modelo.EstadoMembresia;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.method.annotation.AuthenticationPrincipalArgumentResolver;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

@ExtendWith(MockitoExtension.class)
class ControladorAdministracionClientesTest {

    private static final PrincipalPropietario DUENO = new PrincipalPropietario(
            UUID.fromString("d5bb220a-5a66-4bda-bde3-0c3b145d286b"),
            RolCuenta.DUENO, 1, 1, "dueno@example.test");
    private static final PrincipalPropietario OPERADOR = new PrincipalPropietario(
            UUID.fromString("0e715749-91d0-48d2-a8fb-90a944d73ac1"),
            RolCuenta.OPERADOR, 1, 1, "operador@example.test");

    @Mock
    private ServicioAdministracionClientes servicio;

    private MockMvc mvc;

    @BeforeEach
    void preparar() {
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(DUENO, null, List.of()));
        mvc = MockMvcBuilders.standaloneSetup(new ControladorAdministracionClientes(servicio))
                .setCustomArgumentResolvers(new AuthenticationPrincipalArgumentResolver())
                .build();
    }

    @AfterEach
    void limpiarContexto() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void listaUsaRutaParametrosYRespuestaPrivada() throws Exception {
        when(servicio.listar("2", "activa", "Ana", DUENO)).thenReturn(new PaginaClientesAdministracion(
                List.of(new ClienteResumenAdministracion("CLI-1024", "Ana López", EstadoMembresia.ACTIVA)),
                2, 10, 11, 21, 3, "00000000-0000-0000-0000-000000000001:4"));

        mvc.perform(get("/api/v1/clientes/administracion")
                        .param("pagina", "2")
                        .param("estado", "activa")
                        .param("busqueda", "Ana"))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store, private"))
                .andExpect(header().string("Vary", "Cookie"))
                .andExpect(jsonPath("$.items[0].codigo").value("CLI-1024"))
                .andExpect(jsonPath("$.items[0].nombreCompleto").value("Ana López"))
                .andExpect(jsonPath("$.items[0].estadoMembresia").value("ACTIVA"))
                .andExpect(jsonPath("$.pagina").value(2))
                .andExpect(jsonPath("$.tamanoPagina").value(10))
                .andExpect(jsonPath("$.totalClientes").value(11))
                .andExpect(jsonPath("$.totalRegistros").value(21))
                .andExpect(jsonPath("$.totalPaginas").value(3))
                .andExpect(jsonPath("$.cursorEventos").value("00000000-0000-0000-0000-000000000001:4"));
    }

    @Test
    void detalleSinMembresiaIncluyeElCampoNuloYEncabezadosPrivados() throws Exception {
        when(servicio.consultarDetalle("CLI-1024", DUENO)).thenReturn(new DetalleClienteAdministracion(
                "CLI-1024", "Ana López", EstadoMembresia.SIN_MEMBRESIA, null));

        mvc.perform(get("/api/v1/clientes/administracion/CLI-1024"))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store, private"))
                .andExpect(header().string("Vary", "Cookie"))
                .andExpect(jsonPath("$.codigo").value("CLI-1024"))
                .andExpect(jsonPath("$.nombreCompleto").value("Ana López"))
                .andExpect(jsonPath("$.estadoMembresia").value("SIN_MEMBRESIA"))
                .andExpect(jsonPath("$.membresia").value(nullValue()));
    }

    @Test
    void listaYDetalleTambienPasanLaSesionDeOperadorAlServicio() throws Exception {
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(OPERADOR, null, List.of()));
        when(servicio.listar("1", null, null, OPERADOR)).thenReturn(
                new PaginaClientesAdministracion(List.of(), 1, 10, 0, 0, 0, "cursor-operador"));
        when(servicio.consultarDetalle("CLI-1024", OPERADOR)).thenReturn(new DetalleClienteAdministracion(
                "CLI-1024", "Ana López", EstadoMembresia.SIN_MEMBRESIA, null));

        mvc.perform(get("/api/v1/clientes/administracion"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.cursorEventos").value("cursor-operador"));
        mvc.perform(get("/api/v1/clientes/administracion/CLI-1024"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.codigo").value("CLI-1024"));

        verify(servicio).listar("1", null, null, OPERADOR);
        verify(servicio).consultarDetalle("CLI-1024", OPERADOR);
    }

    @Test
    void conservaErroresDeValidacionConEncabezadosPrivados() throws Exception {
        when(servicio.listar("x", null, null, DUENO)).thenThrow(new ErrorConfiguracion(
                HttpStatus.BAD_REQUEST, "No pudimos cargar esa parte de la lista.", "PAGINA_NO_VALIDA"));

        mvc.perform(get("/api/v1/clientes/administracion").param("pagina", "x"))
                .andExpect(status().isBadRequest())
                .andExpect(header().string("Cache-Control", "no-store, private"))
                .andExpect(jsonPath("$.codigo").value("PAGINA_NO_VALIDA"))
                .andExpect(jsonPath("$.mensaje").value("No pudimos cargar esa parte de la lista."));
    }
}
