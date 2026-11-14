package mx.smartparking.api.eventos;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.UUID;
import java.util.stream.Stream;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.ErrorConfiguracionControlador;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.core.MethodParameter;
import org.springframework.http.HttpStatus;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.support.WebDataBinderFactory;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

/** Verifica estados HTTP de errores durante el handshake SSE. */
class ControladorEventosAdministracionTest {

    private ServicioEventosAdministracion servicio;
    private MockMvc mvc;
    private ServicioEventosAdministracion servicioReal;
    private PrincipalPropietario propietario;

    @BeforeEach
    void preparar() {
        servicio = mock(ServicioEventosAdministracion.class);
        propietario = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.DUENO, 1, 1, "dueno@example.test");
        mvc = crearMvc(servicio, propietario);
    }

    @AfterEach
    void detenerServicioReal() {
        if (servicioReal != null) {
            servicioReal.detener();
        }
    }

    @ParameterizedTest
    @MethodSource("erroresDeHandshake")
    void conservaEstadoDelErrorSinExigirJson(HttpStatus estado) throws Exception {
        doThrow(new ErrorConfiguracion(estado, "Handshake rechazado."))
                .when(servicio).abrirStream(anyString(), any(), any());

        mvc.perform(get("/api/v1/eventos/administracion")
                        .session(new MockHttpSession())
                        .accept("text/event-stream"))
                .andExpect(status().is(estado.value()))
                .andExpect(content().string(""));
    }

    @Test
    void limiteDeCincoStreamsPorSesionResponde429EnElHandshakeSse() throws Exception {
        GestorSesionesPropietario gestor = new GestorSesionesPropietario();
        RepositorioCuentas cuentas = mock(RepositorioCuentas.class);
        MockHttpSession sesion = new MockHttpSession();
        gestor.registrar(sesion, propietario);
        when(cuentas.sesionVigente(propietario.cuentaId(), propietario.revisionAcceso(),
                propietario.rol().name(), propietario.revisionPropietario())).thenReturn(true);
        servicioReal = new ServicioEventosAdministracion(gestor, cuentas);
        MockMvc mvcReal = crearMvc(servicioReal, propietario);

        for (int indice = 0; indice < 5; indice++) {
            mvcReal.perform(get("/api/v1/eventos/administracion")
                            .session(sesion)
                            .accept("text/event-stream"))
                    .andExpect(status().isOk())
                    .andExpect(request().asyncStarted());
        }

        mvcReal.perform(get("/api/v1/eventos/administracion")
                        .session(sesion)
                        .accept("text/event-stream"))
                .andExpect(status().isTooManyRequests())
                .andExpect(content().string(""));
    }

    private static Stream<HttpStatus> erroresDeHandshake() {
        return Stream.of(HttpStatus.TOO_MANY_REQUESTS, HttpStatus.UNAUTHORIZED, HttpStatus.FORBIDDEN);
    }

    private static MockMvc crearMvc(
            ServicioEventosAdministracion servicio, PrincipalPropietario propietario) {
        return MockMvcBuilders.standaloneSetup(new ControladorEventosAdministracion(servicio))
                .setControllerAdvice(new ErrorConfiguracionControlador())
                .setCustomArgumentResolvers(new ArgumentoPropietarioResolver(propietario))
                .build();
    }

    private static final class ArgumentoPropietarioResolver implements HandlerMethodArgumentResolver {

        private final PrincipalPropietario propietario;

        private ArgumentoPropietarioResolver(PrincipalPropietario propietario) {
            this.propietario = propietario;
        }

        @Override
        public boolean supportsParameter(MethodParameter parametro) {
            return parametro.hasParameterAnnotation(AuthenticationPrincipal.class);
        }

        @Override
        public Object resolveArgument(
                MethodParameter parametro,
                ModelAndViewContainer contenedor,
                NativeWebRequest solicitud,
                WebDataBinderFactory fabrica) {
            return propietario;
        }
    }
}
