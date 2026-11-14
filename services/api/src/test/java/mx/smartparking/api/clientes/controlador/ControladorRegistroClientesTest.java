package mx.smartparking.api.clientes.controlador;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.core.context.SecurityContextHolder;

@ExtendWith(MockitoExtension.class)
class ControladorRegistroClientesTest extends ControladorClientesTestSupport {

    @Test
    void registroNormalizaCorreoOmiteSegundoApellidoYNoIniciaSesion() throws Exception {
        when(servicioClientes.registrarCliente(
                "Ana María", "Pérez", null, CORREO, "contraseña-segura"))
                .thenReturn(CLIENTE_ID);

        mvc.perform(post("/api/v1/clientes/registro")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"nombres":" Ana María ","primerApellido":" Pérez ",
                                 "correo":" Cliente@Example.Test ","contrasena":"contraseña-segura",
                                 "confirmarContrasena":"contraseña-segura"}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.clienteId").value(CLIENTE_ID.toString()))
                .andExpect(jsonPath("$.correo").value(CORREO))
                .andExpect(header().string("Cache-Control", "no-store, private"))
                .andExpect(header().string("Vary", "Cookie"));

        verify(servicioClientes).registrarCliente(
                "Ana María", "Pérez", null, CORREO, "contraseña-segura");
        verify(administradorAutenticacion, never()).authenticate(any());
        assertTrue(SecurityContextHolder.getContext().getAuthentication() == null);
    }

    @Test
    void registroSoloRequiereUnaContrasenaYConservaMinimoUnicode() throws Exception {
        mvc.perform(post("/api/v1/clientes/registro")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"nombres":"Ana","primerApellido":"Pérez","correo":"ana@example.test",
                                 "contrasena":"ááááááááá"}
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.codigo").value("VALIDACION"));
        verify(servicioClientes, never()).registrarCliente(any(), any(), any(), any(), any());
    }

    @Test
    void registroAceptaUnaContrasenaSinCampoDeConfirmacion() throws Exception {
        when(servicioClientes.registrarCliente(
                "Ana", "Pérez", null, CORREO, "contraseña-segura"))
                .thenReturn(CLIENTE_ID);

        mvc.perform(post("/api/v1/clientes/registro")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"nombres":"Ana","primerApellido":"Pérez","correo":"cliente@example.test",
                                 "contrasena":"contraseña-segura"}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.clienteId").value(CLIENTE_ID.toString()));
    }

    @Test
    void conflictoDeCorreoUsaRespuestaGenerica() throws Exception {
        when(servicioClientes.registrarCliente(
                "Ana", "Pérez", null, CORREO, "contraseña-segura"))
                .thenThrow(new ErrorConfiguracion(
                        HttpStatus.CONFLICT, "correo duplicado: " + CORREO, "REGISTRO_NO_COMPLETADO"));

        mvc.perform(post("/api/v1/clientes/registro")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(cuerpoRegistro(CORREO)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.codigo").value("REGISTRO_NO_DISPONIBLE"))
                .andExpect(jsonPath("$.error").value("No pudimos completar el registro con esos datos."))
                .andExpect(jsonPath("$.error").value(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString(CORREO))));
    }

    @Test
    void registroCuentaPayloadsInvalidosPorHuellaDeCorreo() throws Exception {
        for (int intento = 0; intento < 5; intento++) {
            mvc.perform(post("/api/v1/clientes/registro")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {"nombres":"Ana","primerApellido":"Pérez","correo":" Cuenta@Example.Test ",
                                     "contrasena":"corta","confirmarContrasena":"corta"}
                                    """))
                    .andExpect(status().isBadRequest());
        }

        mvc.perform(post("/api/v1/clientes/registro")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(cuerpoRegistro("cuenta@example.test")))
                .andExpect(status().isTooManyRequests())
                .andExpect(jsonPath("$.codigo").value("INTENTOS_LIMITADOS"));
        verify(servicioClientes, never()).registrarCliente(any(), any(), any(), any(), any());
    }
}
