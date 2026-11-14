package mx.smartparking.api.clientes.controlador;

import java.util.List;
import java.util.UUID;
import mx.smartparking.api.clientes.servicio.ServicioClientes;
import mx.smartparking.api.seguridad.cliente.GestorSesionesCliente;
import mx.smartparking.api.seguridad.cliente.PrincipalCliente;
import mx.smartparking.api.seguridad.cliente.ProteccionIntentosInicioSesionCliente;
import mx.smartparking.api.seguridad.cliente.ProteccionIntentosRegistroCliente;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.mockito.Mock;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.context.SecurityContextRepository;
import org.springframework.security.web.csrf.HttpSessionCsrfTokenRepository;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

/** Fixture compartido por las suites de ControladorClientesTest. */
abstract class ControladorClientesTestSupport {
     static final UUID CLIENTE_ID = UUID.fromString("b971a99f-8350-4fa7-9c15-c44b2a44dceb");
     static final UUID OTRO_CLIENTE_ID = UUID.fromString("640f5ab5-b9c2-4b51-bd4e-a4ebec1830ec");
     static final String CORREO = "cliente@example.test";

    @Mock
     AuthenticationManager administradorAutenticacion;

    @Mock
     SecurityContextRepository repositorioContexto;

    @Mock
     ServicioClientes servicioClientes;

     GestorSesionesCliente gestorSesiones;
     HttpSessionCsrfTokenRepository repositorioCsrf;
     MockMvc mvc;

    @BeforeEach
    void preparar() {
        gestorSesiones = new GestorSesionesCliente();
        repositorioCsrf = new HttpSessionCsrfTokenRepository();
        ControladorClientes controlador = new ControladorClientes(
                administradorAutenticacion,
                repositorioContexto,
                repositorioCsrf,
                gestorSesiones,
                new ProteccionIntentosInicioSesionCliente(),
                new ProteccionIntentosRegistroCliente(),
                servicioClientes);
        mvc = MockMvcBuilders.standaloneSetup(controlador).build();
    }

    @AfterEach
    void limpiarContexto() {
        SecurityContextHolder.clearContext();
    }



     static String cuerpoRegistro(String correo) {
        return """
                {"nombres":"Ana","primerApellido":"Pérez","correo":"%s",
                 "contrasena":"contraseña-segura","confirmarContrasena":"contraseña-segura"}
                """.formatted(correo);
    }

     static UsernamePasswordAuthenticationToken autenticacionCliente(UUID clienteId) {
        return UsernamePasswordAuthenticationToken.authenticated(
                new PrincipalCliente(clienteId, 1L, CORREO), null,
                List.of(new SimpleGrantedAuthority("ROLE_CLIENTE")));
    }
}
