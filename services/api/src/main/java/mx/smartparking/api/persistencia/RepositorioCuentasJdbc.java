package mx.smartparking.api.persistencia;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.configuracion.DatosConfiguracion;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/** Consulta y guarda los cambios de las cuentas en la base de datos. */
@Repository
public class RepositorioCuentasJdbc implements RepositorioCuentas {

    private static final RowMapper<CuentaPersistida> MAPA = RepositorioCuentasJdbc::mapear;

    private final String sqlCrearDueno = CargadorSql.cargar("cuentas/crear_dueno.sql");
    private final String sqlCrearCliente = CargadorSql.cargar("cuentas/crear_cliente.sql");
    private final String sqlActualizarContrasenaCliente =
            CargadorSql.cargar("cuentas/actualizar_contrasena_cliente.sql");
    private final String sqlBuscarActivaPorCorreo = CargadorSql.cargar("cuentas/buscar_activa_por_correo.sql");
    private final String sqlObtener = CargadorSql.cargar("cuentas/obtener.sql");
    private final String sqlDuenoActual = CargadorSql.cargar("cuentas/dueno_actual.sql");
    private final String sqlDesactivar = CargadorSql.cargar("cuentas/desactivar.sql");
    private final String sqlSesionVigente = CargadorSql.cargar("cuentas/sesion_vigente.sql");

    private final JdbcTemplate jdbc;
    private final Clock reloj;

    @Autowired
    public RepositorioCuentasJdbc(JdbcTemplate jdbc) {
        this(jdbc, Clock.systemUTC());
    }

    RepositorioCuentasJdbc(JdbcTemplate jdbc, Clock reloj) {
        this.jdbc = jdbc;
        this.reloj = reloj;
    }

    @Override
    public UUID crearDueno(DatosConfiguracion datos, String hashContrasena) {
        String correo = datos.propietario().correo().trim().toLowerCase(Locale.ROOT);
        UUID id = UUID.randomUUID();
        Instant ahora = reloj.instant();
        try {
            jdbc.update(sqlCrearDueno, id, datos.propietario().nombres(), datos.propietario().primerApellido(),
                    datos.propietario().segundoApellido(), correo, correo, hashContrasena,
                    Timestamp.from(ahora), Timestamp.from(ahora));
        } catch (DuplicateKeyException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                    "Ya existe una cuenta con ese correo.", "CORREO_ACTIVO_EN_USO");
        }
        return id;
    }

    @Override
    public UUID crearCliente(
            String nombres,
            String primerApellido,
            String segundoApellido,
            String correoNormalizado,
            String hashContrasena) {
        UUID id = UUID.randomUUID();
        Timestamp ahora = Timestamp.from(reloj.instant());
        try {
            jdbc.update(sqlCrearCliente, id, nombres, primerApellido, segundoApellido, correoNormalizado,
                    correoNormalizado, hashContrasena, ahora, ahora);
        } catch (DuplicateKeyException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                    "No pudimos completar el registro. Revisa los datos e inténtalo de nuevo.",
                    "REGISTRO_NO_COMPLETADO");
        }
        return id;
    }

    @Override
    public boolean actualizarContrasenaCliente(UUID cuentaId, long revisionEsperada, String hashContrasena) {
        int filas = jdbc.update(
                sqlActualizarContrasenaCliente,
                hashContrasena,
                Timestamp.from(reloj.instant()),
                cuentaId,
                revisionEsperada);
        return filas == 1;
    }

    @Override
    public Optional<CuentaPersistida> buscarActivaPorCorreo(String correoNormalizado) {
        List<CuentaPersistida> cuentas = jdbc.query(sqlBuscarActivaPorCorreo, MAPA, correoNormalizado);
        return cuentas.stream().findFirst();
    }

    @Override
    public Optional<CuentaPersistida> obtener(UUID cuentaId) {
        List<CuentaPersistida> cuentas = jdbc.query(sqlObtener, MAPA, cuentaId);
        return cuentas.stream().findFirst();
    }

    @Override
    public Optional<CuentaPersistida> duenoActual() {
        List<CuentaPersistida> cuentas = jdbc.query(sqlDuenoActual, MAPA);
        return cuentas.stream().findFirst();
    }

    @Override
    public void desactivar(UUID cuentaId) {
        int filas = jdbc.update(sqlDesactivar, Timestamp.from(reloj.instant()), cuentaId);
        if (filas != 1) {
            throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                    "La información de la cuenta cambió. Actualiza la pantalla e inténtalo de nuevo.", "CUENTA_EN_CONFLICTO");
        }
    }

    @Override
    public boolean sesionVigente(
            UUID cuentaId, long revisionAcceso, String rol, long revisionPropietario) {
        Integer filas = jdbc.queryForObject(
                sqlSesionVigente,
                Integer.class,
                cuentaId,
                revisionAcceso,
                rol,
                rol,
                revisionPropietario);
        return filas != null && filas == 1;
    }

    private static CuentaPersistida mapear(ResultSet rs, int fila) throws SQLException {
        return new CuentaPersistida(
                rs.getObject("id", UUID.class), rs.getString("nombres"),
                rs.getString("primer_apellido"), rs.getString("segundo_apellido"),
                rs.getString("correo"), rs.getString("correo_normalizado"),
                RolCuenta.valueOf(rs.getString("rol")), "ACTIVA".equals(rs.getString("estado")),
                rs.getString("hash_contrasena_acceso"), rs.getLong("revision_acceso"));
    }
}
