import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.UUID;
import org.springframework.security.crypto.password.Pbkdf2PasswordEncoder;

/** Genera en privado la cuenta sintética OPERADOR y su fixture SQL descartable. */
public final class FixtureOperator {
    private static final String PREFIJO_HASH = "{pbkdf2@SpringSecurity_v5_8_600k}";

    private FixtureOperator() { }

    public static void main(String[] args) throws Exception {
        Path directorioPrivado = Path.of(args[0]);
        String correo = "qa-operador-" + UUID.randomUUID() + "@example.test";
        String contrasena = UUID.randomUUID() + "Aa9!";
        Pbkdf2PasswordEncoder codificador = new Pbkdf2PasswordEncoder(
                "", 16, 600_000,
                Pbkdf2PasswordEncoder.SecretKeyFactoryAlgorithm.PBKDF2WithHmacSHA256);
        String hash = PREFIJO_HASH + codificador.encode(contrasena);
        if (!codificador.matches(contrasena, hash.substring(PREFIJO_HASH.length()))) {
            throw new IllegalStateException("El hash PBKDF2 sintético no coincide.");
        }

        String credenciales = "{\"correo\":\"" + correo
                + "\",\"contrasena\":\"" + contrasena + "\"}\n";
        String sql = """
                BEGIN;
                DO $fixture_seguro$
                BEGIN
                    IF (SELECT COUNT(*) FROM cuenta
                         WHERE rol = 'DUENO' AND estado = 'ACTIVA'
                           AND correo_normalizado LIKE '%%@example.test') <> 1 THEN
                        RAISE EXCEPTION 'Se requiere exactamente un DUENO sintético activo.';
                    END IF;
                END;
                $fixture_seguro$;
                INSERT INTO empleado (
                    nombres, primer_apellido, segundo_apellido, estado, revision,
                    creado_en, actualizado_en, correo, correo_normalizado)
                VALUES (
                    'QA Seguridad', 'Sintetico', NULL, 'ACTIVO', 1,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '%s', '%s');
                INSERT INTO cuenta (
                    id, nombres, primer_apellido, segundo_apellido, correo, correo_normalizado,
                    rol, estado, hash_contrasena_acceso, revision_acceso,
                    creada_en, actualizada_en, empleado_id)
                SELECT gen_random_uuid(), 'QA Seguridad', 'Sintetico', NULL,
                       e.correo, e.correo_normalizado, 'OPERADOR', 'ACTIVA', '%s', 1,
                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, e.id
                  FROM empleado e
                 WHERE e.correo_normalizado = '%s' AND e.estado = 'ACTIVO';
                DO $fixture_verificacion$
                BEGIN
                    IF (SELECT COUNT(*) FROM cuenta
                         WHERE rol = 'OPERADOR' AND estado = 'ACTIVA'
                           AND correo_normalizado = '%s') <> 1 THEN
                        RAISE EXCEPTION 'No se creó exactamente un OPERADOR sintético.';
                    END IF;
                END;
                $fixture_verificacion$;
                COMMIT;
                """.formatted(correo, correo, hash, correo, correo);

        Path archivoCredenciales = directorioPrivado.resolve("operator-credentials.json");
        Path archivoSql = directorioPrivado.resolve("operator-fixture.sql");
        Files.writeString(archivoCredenciales, credenciales, StandardOpenOption.CREATE_NEW);
        Files.writeString(archivoSql, sql, StandardOpenOption.CREATE_NEW);
        Files.setPosixFilePermissions(archivoCredenciales, PosixFilePermissions.fromString("rw-------"));
        Files.setPosixFilePermissions(archivoSql, PosixFilePermissions.fromString("rw-------"));
        System.out.println("fixture_operador=generado hash_encoder=SpringSecurity_PBKDF2_600k");
    }
}
