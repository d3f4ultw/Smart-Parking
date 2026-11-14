package mx.smartparking.api.seguridad;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.crypto.password.PasswordEncoder;

@ExtendWith(MockitoExtension.class)
class ProveedorAutenticacionPropietarioTest {

    @Mock
    private ProveedorCredencialesPropietario proveedorCredenciales;

    @Mock
    private PasswordEncoder passwordEncoder;

    private ProveedorAutenticacionPropietario proveedorAutenticacion;

    @BeforeEach
    void preparar() {
        when(passwordEncoder.encode(anyString())).thenReturn("hash-ficticio");
        proveedorAutenticacion = new ProveedorAutenticacionPropietario(proveedorCredenciales, passwordEncoder);
    }

    @Test
    void autenticaConContrasenaRegularYDevuelveRevision() {
        when(proveedorCredenciales.buscarPorCorreo("duena@example.test"))
                .thenReturn(Optional.of(new CredencialesPropietario(
                        14L,
                        "duena@example.test",
                        "hash-acceso")));
        when(passwordEncoder.matches("contrasena-segura", "hash-acceso")).thenReturn(true);

        Authentication resultado = proveedorAutenticacion.authenticate(
                UsernamePasswordAuthenticationToken.unauthenticated(
                        "  Duena@Example.Test ",
                        "contrasena-segura"));

        PrincipalPropietario principal = assertInstanceOf(PrincipalPropietario.class, resultado.getPrincipal());
        assertEquals(14L, principal.revisionPropietario());
        assertEquals("duena@example.test", principal.correo());
        verify(passwordEncoder).matches("contrasena-segura", "hash-acceso");
    }

    @Test
    void operadorElegibleRecibeSoloLaAutoridadDerivadaDeLaCuenta() {
        when(proveedorCredenciales.buscarPorCorreo("operador@example.test"))
                .thenReturn(Optional.of(new CredencialesPropietario(
                        UUID.randomUUID(), RolCuenta.OPERADOR, 4L, 0L,
                        "operador@example.test", "hash-acceso")));
        when(passwordEncoder.matches("contrasena-segura", "hash-acceso")).thenReturn(true);

        Authentication resultado = proveedorAutenticacion.authenticate(
                UsernamePasswordAuthenticationToken.unauthenticated(
                        "Operador@Example.Test", "contrasena-segura"));

        PrincipalPropietario principal = assertInstanceOf(PrincipalPropietario.class, resultado.getPrincipal());
        assertEquals(RolCuenta.OPERADOR, principal.rol());
        assertEquals(0L, principal.revisionPropietario());
        assertTrue(resultado.getAuthorities().contains(new SimpleGrantedAuthority("ROLE_OPERADOR")));
        assertEquals(1, resultado.getAuthorities().size());
        verify(passwordEncoder).matches("contrasena-segura", "hash-acceso");
    }

    @Test
    void rechazaLaContrasenaAdministrativaAlIniciarSesion() {
        when(proveedorCredenciales.buscarPorCorreo("duena@example.test"))
                .thenReturn(Optional.of(new CredencialesPropietario(
                        14L,
                        "duena@example.test",
                        "hash-acceso")));
        when(passwordEncoder.matches("contrasena-administrativa", "hash-acceso")).thenReturn(false);

        BadCredentialsException excepcion = assertThrows(
                BadCredentialsException.class,
                () -> proveedorAutenticacion.authenticate(
                        UsernamePasswordAuthenticationToken.unauthenticated(
                                "duena@example.test",
                                "contrasena-administrativa")));

        assertEquals("Credenciales no válidas.", excepcion.getMessage());
        verify(passwordEncoder).matches("contrasena-administrativa", "hash-acceso");
    }

    @Test
    void correoInexistenteUsaVerificacionFicticiaYRespuestaGenerica() {
        when(proveedorCredenciales.buscarPorCorreo("ausente@example.test"))
                .thenReturn(Optional.empty());
        when(passwordEncoder.matches("contrasena", "hash-ficticio")).thenReturn(false);

        BadCredentialsException excepcion = assertThrows(
                BadCredentialsException.class,
                () -> proveedorAutenticacion.authenticate(
                        UsernamePasswordAuthenticationToken.unauthenticated(
                                "ausente@example.test",
                                "contrasena")));

        assertEquals("Credenciales no válidas.", excepcion.getMessage());
        verify(passwordEncoder, never()).matches("contrasena", "hash-acceso");
    }
}
