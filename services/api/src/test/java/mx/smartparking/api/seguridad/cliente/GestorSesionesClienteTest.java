package mx.smartparking.api.seguridad.cliente;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpSession;

class GestorSesionesClienteTest {

    @Test
    void cambioDeContrasenaRevocaSoloLaCuentaClienteIndicada() {
        GestorSesionesCliente gestor = new GestorSesionesCliente();
        UUID cuentaCliente = UUID.randomUUID();
        UUID otraCuenta = UUID.randomUUID();
        PrincipalCliente principal = new PrincipalCliente(cuentaCliente, 1L, "cliente@example.test");
        PrincipalCliente otroPrincipal = new PrincipalCliente(otraCuenta, 4L, "otro@example.test");
        MockHttpSession primeraSesion = new MockHttpSession();
        MockHttpSession segundaSesion = new MockHttpSession();
        MockHttpSession sesionAjena = new MockHttpSession();
        gestor.registrar(primeraSesion, principal);
        gestor.registrar(segundaSesion, principal);
        gestor.registrar(sesionAjena, otroPrincipal);

        gestor.revocarCuenta(cuentaCliente);

        assertTrue(primeraSesion.isInvalid());
        assertTrue(segundaSesion.isInvalid());
        assertFalse(sesionAjena.isInvalid());
        assertFalse(gestor.estaRegistrada(primeraSesion.getId(), principal));
        assertTrue(gestor.estaRegistrada(sesionAjena.getId(), otroPrincipal));
    }
}
