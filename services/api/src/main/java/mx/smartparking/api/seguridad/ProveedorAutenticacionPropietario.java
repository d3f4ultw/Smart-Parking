package mx.smartparking.api.seguridad;

import java.util.Locale;
import java.util.Optional;
import org.springframework.security.authentication.AuthenticationProvider;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

/** Comprueba la contraseña de acceso del propietario o de un operador que tiene permiso para entrar. */
@Component
public class ProveedorAutenticacionPropietario implements AuthenticationProvider {

    private static final String MARCADOR_CREDENCIALES_INVALIDAS = "Credenciales no válidas.";

    private final ProveedorCredencialesPropietario proveedorCredenciales;
    private final PasswordEncoder passwordEncoder;
    private final String hashFicticio;

    /**
     * Prepara una comprobación para que un correo inexistente tarde un tiempo parecido al de uno
     * registrado.
     */
    public ProveedorAutenticacionPropietario(
            ProveedorCredencialesPropietario proveedorCredenciales,
            PasswordEncoder passwordEncoder) {
        this.proveedorCredenciales = proveedorCredenciales;
        this.passwordEncoder = passwordEncoder;
        this.hashFicticio = passwordEncoder.encode("verificador-ficticio-no-utilizable");
    }

    /** Comprueba que el correo y la contraseña correspondan a una cuenta con acceso permitido. */
    @Override
    public Authentication authenticate(Authentication autenticacion) throws AuthenticationException {
        String correoNormalizado = normalizarCorreo(autenticacion.getName());
        Object credenciales = autenticacion.getCredentials();
        String contrasena = credenciales instanceof String texto ? texto : "";

        Optional<CredencialesPropietario> resultado = proveedorCredenciales.buscarPorCorreo(correoNormalizado);
        if (resultado.isEmpty()) {
            passwordEncoder.matches(contrasena, hashFicticio);
            throw new BadCredentialsException(MARCADOR_CREDENCIALES_INVALIDAS);
        }

        CredencialesPropietario datos = resultado.get();
        if (!passwordEncoder.matches(contrasena, datos.hashContrasenaAcceso())) {
            throw new BadCredentialsException(MARCADOR_CREDENCIALES_INVALIDAS);
        }

        PrincipalPropietario principal = new PrincipalPropietario(
                datos.cuentaId(), datos.rol(), datos.revisionAcceso(), datos.revisionPropietario(),
                normalizarCorreo(datos.correo()));
        return UsernamePasswordAuthenticationToken.authenticated(
                principal, null, java.util.List.of(new org.springframework.security.core.authority.SimpleGrantedAuthority(
                        "ROLE_" + datos.rol().name())));
    }

    @Override
    public boolean supports(Class<?> tipoAutenticacion) {
        return UsernamePasswordAuthenticationToken.class.isAssignableFrom(tipoAutenticacion);
    }

    private String normalizarCorreo(String correo) {
        return correo == null ? "" : correo.trim().toLowerCase(Locale.ROOT);
    }
}
