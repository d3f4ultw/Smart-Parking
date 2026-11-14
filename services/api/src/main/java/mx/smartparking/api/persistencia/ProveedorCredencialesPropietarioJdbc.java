package mx.smartparking.api.persistencia;

import java.util.List;
import java.util.Locale;
import java.util.Optional;
import mx.smartparking.api.seguridad.CredencialesPropietario;
import mx.smartparking.api.seguridad.ProveedorCredencialesPropietario;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Busca los datos necesarios para que un propietario u operador autorizado pueda iniciar sesión. */
@Repository
public class ProveedorCredencialesPropietarioJdbc implements ProveedorCredencialesPropietario {

    private final JdbcTemplate jdbcTemplate;
    private final String sqlBuscarPorCorreo = CargadorSql.cargar("cuentas/buscar_credenciales_propietario.sql");

    public ProveedorCredencialesPropietarioJdbc(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public Optional<CredencialesPropietario> buscarPorCorreo(String correoNormalizado) {
        if (correoNormalizado == null || correoNormalizado.isBlank()) {
            return Optional.empty();
        }
        String correo = correoNormalizado.trim().toLowerCase(Locale.ROOT);
        List<CredencialesPropietario> resultados = jdbcTemplate.query(sqlBuscarPorCorreo,
                (rs, fila) -> new CredencialesPropietario(
                        rs.getObject("id", java.util.UUID.class),
                        mx.smartparking.api.seguridad.RolCuenta.valueOf(rs.getString("rol")),
                        rs.getLong("revision_acceso"),
                        rs.getLong("revision_propietario"),
                        rs.getString("correo"),
                        rs.getString("hash_contrasena_acceso")),
                correo, correo);
        return resultados.stream().findFirst();
    }
}
