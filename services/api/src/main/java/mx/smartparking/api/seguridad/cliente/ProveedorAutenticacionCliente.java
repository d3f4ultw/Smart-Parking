package mx.smartparking.api.seguridad.cliente;

import java.util.List;
import java.util.Locale;
import java.util.Optional;
import mx.smartparking.api.persistencia.CuentaPersistida;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.security.authentication.AuthenticationProvider;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

/** Comprueba la contraseña de acceso de las cuentas de cliente. */
@Component
public final class ProveedorAutenticacionCliente implements AuthenticationProvider {

    private static final String ERROR_CREDENCIALES = "Credenciales no válidas.";
    private static final String ROL_CLIENTE = "ROLE_CLIENTE";

    private final RepositorioCuentas cuentas;
    private final PasswordEncoder passwordEncoder;
    private final String hashFicticio;

    public ProveedorAutenticacionCliente(RepositorioCuentas cuentas, PasswordEncoder passwordEncoder) {
        this.cuentas = cuentas;
        this.passwordEncoder = passwordEncoder;
        this.hashFicticio = passwordEncoder.encode("verificador-ficticio-no-utilizable");
    }

    @Override
    public Authentication authenticate(Authentication autenticacion) throws AuthenticationException {
        String correo = normalizarCorreo(autenticacion.getName());
        Object credenciales = autenticacion.getCredentials();
        String contrasena = credenciales instanceof String texto ? texto : "";
        Optional<CuentaPersistida> resultado = cuentas.buscarActivaPorCorreo(correo);

        if (resultado.isEmpty()) {
            passwordEncoder.matches(contrasena, hashFicticio);
            throw new BadCredentialsException(ERROR_CREDENCIALES);
        }

        CuentaPersistida cuenta = resultado.get();
        if (!cuenta.activa() || cuenta.rol() != RolCuenta.CLIENTE
                || cuenta.hashContrasenaAcceso() == null) {
            passwordEncoder.matches(contrasena, hashFicticio);
            throw new BadCredentialsException(ERROR_CREDENCIALES);
        }
        if (!passwordEncoder.matches(contrasena, cuenta.hashContrasenaAcceso())) {
            throw new BadCredentialsException(ERROR_CREDENCIALES);
        }

        PrincipalCliente principal = new PrincipalCliente(
                cuenta.id(), cuenta.revisionAcceso(), normalizarCorreo(cuenta.correo()));
        return UsernamePasswordAuthenticationToken.authenticated(
                principal, null, List.of(new SimpleGrantedAuthority(ROL_CLIENTE)));
    }

    @Override
    public boolean supports(Class<?> tipoAutenticacion) {
        return UsernamePasswordAuthenticationToken.class.isAssignableFrom(tipoAutenticacion);
    }

    private String normalizarCorreo(String correo) {
        return correo == null ? "" : correo.trim().toLowerCase(Locale.ROOT);
    }
}
