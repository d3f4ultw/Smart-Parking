import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.UUID;

/** Genera en privado credenciales de una cuenta CLIENTE descartable. */
public final class FixtureCliente {
    private FixtureCliente() { }

    public static void main(String[] args) throws Exception {
        Path directorioPrivado = Path.of(args[0]);
        String correo = "qa-cliente-" + UUID.randomUUID() + "@example.test";
        String contrasena = UUID.randomUUID() + "Aa9!";
        String credenciales = "{\"correo\":\"" + correo
                + "\",\"contrasena\":\"" + contrasena + "\"}\n";
        Path archivoCredenciales = directorioPrivado.resolve("client-credentials.json");
        Files.writeString(archivoCredenciales, credenciales, StandardOpenOption.CREATE_NEW);
        Files.setPosixFilePermissions(archivoCredenciales, PosixFilePermissions.fromString("rw-------"));
        System.out.println("fixture_cliente_credenciales=generadas");
    }
}
