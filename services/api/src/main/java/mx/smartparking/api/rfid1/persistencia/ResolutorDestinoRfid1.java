package mx.smartparking.api.rfid1.persistencia;

import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.DestinoRfid1Persistido;

import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import mx.smartparking.api.persistencia.CargadorSql;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/** Resuelve el código público y deriva la membresía del cliente con la misma regla que Administración. */
@Component
public final class ResolutorDestinoRfid1 {

    private static final Pattern CODIGO_CLIENTE = Pattern.compile("CLI-([0-9]{4,})");
    private static final Pattern CODIGO_EMPLEADO = Pattern.compile("E-([0-9]{4,})");

    private final JdbcTemplate jdbc;
    private final String sqlResolverCliente;
    private final String sqlResolverEmpleado;

    public ResolutorDestinoRfid1(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
        this.sqlResolverCliente = CargadorSql.cargar("rfid1/resolver_cliente.sql");
        this.sqlResolverEmpleado = CargadorSql.cargar("rfid1/resolver_empleado.sql");
    }

    public Optional<DestinoRfid1Persistido> resolver(String tipoEntidad, String codigoPersona) {
        if ("CLIENTE".equals(tipoEntidad)) {
            return resolverCliente(codigoPersona);
        }
        if ("EMPLEADO".equals(tipoEntidad)) {
            return resolverEmpleado(codigoPersona);
        }
        return Optional.empty();
    }

    private Optional<DestinoRfid1Persistido> resolverCliente(String codigoPersona) {
        Long numero = extraerNumero(CODIGO_CLIENTE, codigoPersona);
        if (numero == null) {
            return Optional.empty();
        }
        List<DestinoRfid1Persistido> destinos = jdbc.query(sqlResolverCliente, (rs, fila) -> {
            long numeroLeido = rs.getLong("numero");
            return new DestinoRfid1Persistido(
                    "CLIENTE", String.format(Locale.ROOT, "CLI-%04d", numeroLeido),
                    rs.getObject("cliente_id", UUID.class), null,
                    "ACTIVA".equals(rs.getString("estado")), rs.getString("estado_membresia"));
        }, numero);
        return destinos.stream().filter(destino -> destino.codigoPersona().equals(codigoPersona)).findFirst();
    }

    private Optional<DestinoRfid1Persistido> resolverEmpleado(String codigoPersona) {
        Long id = extraerNumero(CODIGO_EMPLEADO, codigoPersona);
        if (id == null) {
            return Optional.empty();
        }
        List<DestinoRfid1Persistido> destinos = jdbc.query(sqlResolverEmpleado, (rs, fila) -> {
            long idLeido = rs.getLong("id");
            return new DestinoRfid1Persistido(
                    "EMPLEADO", String.format(Locale.ROOT, "E-%04d", idLeido), null, idLeido,
                    "ACTIVO".equals(rs.getString("estado")), null);
        }, id);
        return destinos.stream().filter(destino -> destino.codigoPersona().equals(codigoPersona)).findFirst();
    }

    private static Long extraerNumero(Pattern patron, String codigoPersona) {
        if (codigoPersona == null) {
            return null;
        }
        Matcher matcher = patron.matcher(codigoPersona);
        if (!matcher.matches()) {
            return null;
        }
        try {
            return Long.parseLong(matcher.group(1));
        } catch (NumberFormatException excepcion) {
            return null;
        }
    }
}
