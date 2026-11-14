package mx.smartparking.api.persistencia;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/** Guarda los cambios de las invitaciones y de las cuentas de operador en la base de datos. */
@Repository
public class RepositorioActivacionOperadorJdbc implements RepositorioActivacionOperador {

    private static final RowMapper<InvitacionOperadorPersistida> MAPA_INVITACION =
            RepositorioActivacionOperadorJdbc::mapearInvitacion;
    private static final RowMapper<CuentaActivacionOperador> MAPA_CUENTA =
            RepositorioActivacionOperadorJdbc::mapearCuenta;

    private final JdbcTemplate jdbc;
    private final String sqlCrearInvitacionInicial =
            CargadorSql.cargar("operadores/crear_invitacion_inicial.sql");
    private final String sqlBuscarInvitacionPorTokenHash =
            CargadorSql.cargar("operadores/buscar_invitacion_por_token_hash.sql");
    private final String sqlBuscarEmpleadoId =
            CargadorSql.cargar("operadores/buscar_empleado_id_operador.sql");
    private final String sqlBloquearCuentaOperador =
            CargadorSql.cargar("operadores/bloquear_cuenta_operador.sql");
    private final String sqlBloquearInvitacionOperador =
            CargadorSql.cargar("operadores/bloquear_invitacion.sql");
    private final String sqlActivarOperador = CargadorSql.cargar("operadores/activar_operador.sql");
    private final String sqlConsumirInvitacion = CargadorSql.cargar("operadores/consumir_invitacion.sql");
    private final String sqlActualizarResultadoEnvio =
            CargadorSql.cargar("operadores/actualizar_resultado_envio_invitacion.sql");
    private final String sqlConsultarEstadoEnvio =
            CargadorSql.cargar("operadores/consultar_estado_envio_invitacion.sql");

    public RepositorioActivacionOperadorJdbc(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public void crearInicial(UUID operadorId, String tokenHash, Instant generadoEn, Instant venceEn) {
        jdbc.update(sqlCrearInvitacionInicial,
                operadorId, tokenHash, tiempo(generadoEn), tiempo(venceEn), tiempo(generadoEn));
    }

    @Override
    public Optional<InvitacionOperadorPersistida> buscarPorTokenHash(String tokenHash) {
        List<InvitacionOperadorPersistida> invitaciones =
                jdbc.query(sqlBuscarInvitacionPorTokenHash, MAPA_INVITACION, tokenHash);
        return invitaciones.stream().findFirst();
    }

    @Override
    public Optional<Long> empleadoId(UUID operadorId) {
        List<Long> ids = jdbc.query(
                sqlBuscarEmpleadoId, (rs, fila) -> (Long) rs.getObject("empleado_id"), operadorId);
        return ids.stream().findFirst();
    }

    @Override
    public Optional<CuentaActivacionOperador> bloquearCuenta(UUID operadorId) {
        try {
            return Optional.of(jdbc.queryForObject(sqlBloquearCuentaOperador, MAPA_CUENTA, operadorId));
        } catch (EmptyResultDataAccessException excepcion) {
            return Optional.empty();
        }
    }

    @Override
    public Optional<InvitacionOperadorPersistida> bloquearInvitacion(UUID operadorId) {
        try {
            return Optional.of(jdbc.queryForObject(sqlBloquearInvitacionOperador, MAPA_INVITACION, operadorId));
        } catch (EmptyResultDataAccessException excepcion) {
            return Optional.empty();
        }
    }

    @Override
    public boolean activar(UUID operadorId, long revisionEsperada, String hashContrasena, Instant ahora) {
        int filas = jdbc.update(
                sqlActivarOperador, hashContrasena, tiempo(ahora), operadorId, revisionEsperada);
        return filas == 1;
    }

    @Override
    public boolean consumir(UUID operadorId, String tokenHash, Instant ahora) {
        int filas = jdbc.update(
                sqlConsumirInvitacion, tiempo(ahora), operadorId, tokenHash, tiempo(ahora));
        return filas == 1;
    }

    @Override
    public Optional<ResultadoActualizacionEnvio> actualizarResultadoEnvio(
            UUID operadorId, String tokenHashEsperado, EstadoEnvioInvitacion estado) {
        List<ResultadoActualizacionEnvio> actualizaciones = jdbc.query(sqlActualizarResultadoEnvio, (rs, fila) -> {
                    EstadoEnvioInvitacion actual = EstadoEnvioInvitacion.valueOf(rs.getString("estado_envio"));
                    Instant consumidoEn = instante(rs, "consumido_en");
                    Instant venceEn = instante(rs, "vence_en");
                    Instant ahora = instante(rs, "ahora");
                    boolean cambioVisible = !estadoDirectorio(EstadoEnvioInvitacion.ENVIANDO,
                            consumidoEn, venceEn, ahora).equals(estadoDirectorio(actual, consumidoEn, venceEn, ahora));
                    return new ResultadoActualizacionEnvio(actual, true, cambioVisible);
                }, estado.name(), operadorId, tokenHashEsperado);
        if (!actualizaciones.isEmpty()) {
            return Optional.of(actualizaciones.get(0));
        }
        List<EstadoEnvioInvitacion> estados = jdbc.query(
                sqlConsultarEstadoEnvio,
                (rs, fila) -> EstadoEnvioInvitacion.valueOf(rs.getString("estado_envio")), operadorId);
        return estados.stream().findFirst()
                .map(actual -> new ResultadoActualizacionEnvio(actual, false, false));
    }

    private static String estadoDirectorio(
            EstadoEnvioInvitacion estadoEnvio, Instant consumidoEn, Instant venceEn, Instant ahora) {
        if (consumidoEn != null) {
            return "CONSUMIDA";
        }
        return !ahora.isBefore(venceEn) ? "EXPIRADA" : estadoEnvio.name();
    }

    private static InvitacionOperadorPersistida mapearInvitacion(ResultSet rs, int fila) throws SQLException {
        return new InvitacionOperadorPersistida(
                rs.getObject("operador_id", UUID.class),
                rs.getString("token_hash"),
                instante(rs, "generado_en"),
                instante(rs, "vence_en"),
                instante(rs, "consumido_en"),
                EstadoEnvioInvitacion.valueOf(rs.getString("estado_envio")),
                instante(rs, "intento_iniciado_en"));
    }

    private static CuentaActivacionOperador mapearCuenta(ResultSet rs, int fila) throws SQLException {
        return new CuentaActivacionOperador(
                rs.getObject("id", UUID.class),
                RolCuenta.valueOf(rs.getString("rol")),
                rs.getString("estado"),
                rs.getString("correo"),
                rs.getString("hash_contrasena_acceso"),
                rs.getLong("revision_acceso"),
                (Long) rs.getObject("empleado_id"));
    }

    private static Instant instante(ResultSet rs, String columna) throws SQLException {
        Timestamp valor = rs.getTimestamp(columna);
        return valor == null ? null : valor.toInstant();
    }

    private static Timestamp tiempo(Instant instante) {
        return Timestamp.from(instante);
    }
}
