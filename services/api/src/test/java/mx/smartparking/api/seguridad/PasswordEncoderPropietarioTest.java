package mx.smartparking.api.seguridad;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;
import org.springframework.security.crypto.password.PasswordEncoder;

class PasswordEncoderPropietarioTest {

    @Test
    void conservaLos128CaracteresEnElHashAdaptativoVersionado() {
        PasswordEncoder passwordEncoder = new ConfiguracionSeguridadPropietario().passwordEncoder();
        String contrasena = "á".repeat(128);
        String hash = passwordEncoder.encode(contrasena);

        assertTrue(hash.startsWith("{pbkdf2@SpringSecurity_v5_8_600k}"));
        assertTrue(passwordEncoder.matches(contrasena, hash));
        assertFalse(passwordEncoder.matches(contrasena.substring(0, 127) + "b", hash));
    }
}
