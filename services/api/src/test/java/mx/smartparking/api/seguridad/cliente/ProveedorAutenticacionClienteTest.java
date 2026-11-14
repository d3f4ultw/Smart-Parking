package mx.smartparking.api.seguridad.cliente;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.persistencia.CuentaPersistida;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.crypto.password.PasswordEncoder;

@ExtendWith(MockitoExtension.class)
class ProveedorAutenticacionClienteTest {

    private static final UUID CUENTA_ID = UUID.fromString("991aa88a-21b6-43f0-b694-ddfeb446c74e");
    private static final String CORREO = "cliente@example.test";

    @Mock
    private RepositorioCuentas cuentas;

    @Mock
    private PasswordEncoder codificador;

    private ProveedorAutenticacionCliente proveedor;

    @BeforeEach
    void preparar() {
        when(codificador.encode(anyString())).thenReturn("hash-ficticio");
        proveedor = new ProveedorAutenticacionCliente(cuentas, codificador);
    }

    @Test
    void autenticaSoloClienteYConservaIdYRevision() {
        when(cuentas.buscarActivaPorCorreo(CORREO))
                .thenReturn(Optional.of(cuenta(RolCuenta.CLIENTE, true, "hash-cliente", 8L)));
        when(codificador.matches("contrasena-segura", "hash-cliente")).thenReturn(true);

        Authentication resultado = proveedor.authenticate(
                UsernamePasswordAuthenticationToken.unauthenticated(
                        " Cliente@Example.Test ", "contrasena-segura"));

        PrincipalCliente principal = assertInstanceOf(PrincipalCliente.class, resultado.getPrincipal());
        assertEquals(CUENTA_ID, principal.cuentaId());
        assertEquals(8L, principal.revisionAcceso());
        assertEquals(CORREO, principal.correo());
        assertEquals("ROLE_CLIENTE", resultado.getAuthorities().iterator().next().getAuthority());
    }

    @Test
    void duenoRecibeElMismoRechazoGenericoQueCorreoInexistente() {
        when(cuentas.buscarActivaPorCorreo(CORREO))
                .thenReturn(Optional.of(cuenta(RolCuenta.DUENO, true, "hash-dueno", 2L)));
        when(codificador.matches("clave", "hash-ficticio")).thenReturn(false);

        BadCredentialsException rechazo = assertThrows(BadCredentialsException.class,
                () -> autenticar("clave"));

        assertEquals("Credenciales no válidas.", rechazo.getMessage());
    }

    @Test
    void operadorYClienteInactivoNoAutentican() {
        when(cuentas.buscarActivaPorCorreo(CORREO))
                .thenReturn(Optional.of(cuenta(RolCuenta.OPERADOR, true, "hash-operador", 2L)));
        when(codificador.matches("clave", "hash-ficticio")).thenReturn(false);
        BadCredentialsException operador = assertThrows(BadCredentialsException.class,
                () -> autenticar("clave"));
        assertEquals("Credenciales no válidas.", operador.getMessage());

        when(cuentas.buscarActivaPorCorreo(CORREO))
                .thenReturn(Optional.of(cuenta(RolCuenta.CLIENTE, false, "hash-cliente", 2L)));
        BadCredentialsException inactivo = assertThrows(BadCredentialsException.class,
                () -> autenticar("clave"));
        assertEquals("Credenciales no válidas.", inactivo.getMessage());
    }

    @Test
    void correoInexistenteUsaHashFicticio() {
        when(cuentas.buscarActivaPorCorreo(CORREO)).thenReturn(Optional.empty());
        when(codificador.matches("clave", "hash-ficticio")).thenReturn(false);

        BadCredentialsException rechazo = assertThrows(BadCredentialsException.class,
                () -> autenticar("clave"));

        assertEquals("Credenciales no válidas.", rechazo.getMessage());
    }

    private Authentication autenticar(String contrasena) {
        return proveedor.authenticate(UsernamePasswordAuthenticationToken.unauthenticated(CORREO, contrasena));
    }

    private CuentaPersistida cuenta(RolCuenta rol, boolean activa, String hash, long revision) {
        return new CuentaPersistida(CUENTA_ID, "Ana", "Pérez", null, CORREO, CORREO,
                rol, activa, hash, revision);
    }
}
