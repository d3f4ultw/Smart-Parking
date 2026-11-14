package mx.smartparking.api.persistencia;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/** Guarda las acciones administrativas y la información necesaria para las invitaciones de operadores. */
@Repository
public class RepositorioAccionesOperadorJdbc implements RepositorioAccionesOperador {

    private static final RowMapper<InvitacionOperadorPersistida> MAPA_INVITACION =
            RepositorioAccionesOperadorJdbc::mapearInvitacion;
    private static final RowMapper<RecuperacionContrasenaOperadorPersistida> MAPA_RECUPERACION =
            RepositorioAccionesOperadorJdbc::mapearRecuperacion;
    private static final RowMapper<AccionOperadorPersistida> MAPA_ACCION =
            RepositorioAccionesOperadorJdbc::mapearAccion;

    private final JdbcTemplate jdbc;
    private final String sqlConsultarInvitacion = CargadorSql.cargar("operadores/consultar_invitacion.sql");
    private final String sqlBloquearInvitacion = CargadorSql.cargar("operadores/bloquear_invitacion.sql");
    private final String sqlConsultarRecuperacion = CargadorSql.cargar("operadores/consultar_recuperacion.sql");
    private final String sqlBloquearRecuperacion = CargadorSql.cargar("operadores/bloquear_recuperacion.sql");
    private final String sqlBuscarRecuperacionPorHash =
            CargadorSql.cargar("operadores/buscar_recuperacion_por_hash.sql");
    private final String sqlConsultarAccion = CargadorSql.cargar("operadores/consultar_accion.sql");
    private final String sqlBloquearAccion = CargadorSql.cargar("operadores/bloquear_accion.sql");
    private final String sqlBloquearAcciones = CargadorSql.cargar("operadores/bloquear_acciones.sql");
    private final String sqlContarAcciones = CargadorSql.cargar("operadores/contar_acciones.sql");
    private final String sqlConsultarUltimaAccion = CargadorSql.cargar("operadores/consultar_ultima_accion.sql");
    private final String sqlInsertarAccion = CargadorSql.cargar("operadores/insertar_accion.sql");
    private final String sqlReemplazarInvitacion = CargadorSql.cargar("operadores/reemplazar_invitacion.sql");
    private final String sqlPrepararInvitacion = CargadorSql.cargar("operadores/preparar_invitacion.sql");
    private final String sqlCrearRecuperacion = CargadorSql.cargar("operadores/crear_recuperacion.sql");
    private final String sqlConsumirRecuperacion = CargadorSql.cargar("operadores/consumir_recuperacion.sql");
    private final String sqlActualizarContrasena =
            CargadorSql.cargar("operadores/actualizar_contrasena_operador.sql");
    private final String sqlInvalidarInvitacion = CargadorSql.cargar("operadores/invalidar_invitacion.sql");
    private final String sqlInvalidarRecuperacion = CargadorSql.cargar("operadores/invalidar_recuperacion.sql");
    private final String sqlActualizarEstadoAccion =
            CargadorSql.cargar("operadores/actualizar_estado_accion.sql");

    public RepositorioAccionesOperadorJdbc(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<InvitacionOperadorPersistida> consultarInvitacion(UUID operadorId) {
        return buscarInvitacion(operadorId, false);
    }

    @Override
    public Optional<InvitacionOperadorPersistida> bloquearInvitacion(UUID operadorId) {
        return buscarInvitacion(operadorId, true);
    }

    private Optional<InvitacionOperadorPersistida> buscarInvitacion(UUID operadorId, boolean bloquear) {
        String sql = bloquear ? sqlBloquearInvitacion : sqlConsultarInvitacion;
        try {
            return Optional.of(jdbc.queryForObject(sql, MAPA_INVITACION, operadorId));
        } catch (EmptyResultDataAccessException excepcion) {
            return Optional.empty();
        }
    }

    @Override
    public Optional<RecuperacionContrasenaOperadorPersistida> consultarRecuperacion(UUID operadorId) {
        return buscarRecuperacion(operadorId, false);
    }

    @Override
    public Optional<RecuperacionContrasenaOperadorPersistida> bloquearRecuperacion(UUID operadorId) {
        return buscarRecuperacion(operadorId, true);
    }

    private Optional<RecuperacionContrasenaOperadorPersistida> buscarRecuperacion(
            UUID operadorId, boolean bloquear) {
        String sql = bloquear ? sqlBloquearRecuperacion : sqlConsultarRecuperacion;
        try {
            return Optional.of(jdbc.queryForObject(sql, MAPA_RECUPERACION, operadorId));
        } catch (EmptyResultDataAccessException excepcion) {
            return Optional.empty();
        }
    }

    @Override
    public Optional<RecuperacionContrasenaOperadorPersistida> buscarRecuperacionPorHash(String tokenHash) {
        List<RecuperacionContrasenaOperadorPersistida> filas =
                jdbc.query(sqlBuscarRecuperacionPorHash, MAPA_RECUPERACION, tokenHash);
        return filas.stream().findFirst();
    }

    @Override
    public Optional<AccionOperadorPersistida> buscarAccion(UUID operadorId, String operacion, String claveHash) {
        return buscarAccion(operadorId, operacion, claveHash, false);
    }

    @Override
    public Optional<AccionOperadorPersistida> bloquearAccion(UUID operadorId, String operacion, String claveHash) {
        return buscarAccion(operadorId, operacion, claveHash, true);
    }

    private Optional<AccionOperadorPersistida> buscarAccion(
            UUID operadorId, String operacion, String claveHash, boolean bloquear) {
        String sql = bloquear ? sqlBloquearAccion : sqlConsultarAccion;
        List<AccionOperadorPersistida> filas = jdbc.query(sql, MAPA_ACCION, operadorId, operacion, claveHash);
        return filas.stream().findFirst();
    }

    @Override
    public void bloquearAcciones(UUID operadorId) {
        jdbc.query(sqlBloquearAcciones, (rs, fila) -> rs.getString(1), operadorId);
    }

    @Override
    public int contarAcciones(UUID operadorId, String operacion, Instant desde) {
        Integer cantidad = jdbc.queryForObject(sqlContarAcciones, Integer.class, operadorId, operacion, tiempo(desde));
        return cantidad == null ? 0 : cantidad;
    }

    @Override
    public Optional<Instant> ultimaAccion(UUID operadorId, String operacion) {
        List<Instant> fechas = jdbc.query(
                sqlConsultarUltimaAccion, (rs, fila) -> instante(rs, "creada_en"), operadorId, operacion);
        return fechas.stream().findFirst();
    }

    @Override
    public Optional<Instant> primeraAccion(UUID operadorId, List<String> operaciones, Instant desde) {
        if (operaciones == null || operaciones.isEmpty()) {
            return Optional.empty();
        }
        String marcadores = String.join(",", java.util.Collections.nCopies(operaciones.size(), "?"));
        String sql = "SELECT creada_en FROM idempotencia_accion_operador "
                + "WHERE operador_id = ? AND operacion IN (" + marcadores + ") AND creada_en >= ? "
                + "ORDER BY creada_en ASC LIMIT 1";
        Object[] parametros = new Object[operaciones.size() + 2];
        parametros[0] = operadorId;
        for (int indice = 0; indice < operaciones.size(); indice++) {
            parametros[indice + 1] = operaciones.get(indice);
        }
        parametros[parametros.length - 1] = tiempo(desde);
        List<Instant> fechas = jdbc.query(sql, (rs, fila) -> instante(rs, "creada_en"), parametros);
        return fechas.stream().findFirst();
    }

    @Override
    public boolean insertarAccion(UUID operadorId, String operacion, String claveHash, Instant creadaEn,
                                  EstadoEnvioInvitacion estadoEnvio, Long revisionAcceso, Instant venceEn) {
        return jdbc.update(sqlInsertarAccion, operadorId, operacion, claveHash, tiempo(creadaEn), estadoEnvio.name(),
                revisionAcceso, tiempo(venceEn)) == 1;
    }

    @Override
    public boolean reemplazarInvitacion(UUID operadorId, String tokenHashEsperado, String tokenHashNuevo,
                                        Instant generadaEn, Instant venceEn, Instant intentoIniciadoEn) {
        return jdbc.update(sqlReemplazarInvitacion, tokenHashNuevo, tiempo(generadaEn), tiempo(venceEn),
                tiempo(intentoIniciadoEn),
                operadorId, tokenHashEsperado) == 1;
    }

    @Override
    public boolean prepararInvitacion(UUID operadorId, String tokenHashNuevo, Instant generadaEn,
                                      Instant venceEn, Instant intentoIniciadoEn) {
        return jdbc.update(sqlPrepararInvitacion, tokenHashNuevo, tiempo(generadaEn), tiempo(venceEn),
                tiempo(intentoIniciadoEn),
                operadorId) == 1;
    }

    @Override
    public boolean crearRecuperacion(UUID operadorId, String tokenHash, Instant generadaEn,
                                     Instant venceEn, Instant intentoIniciadoEn) {
        return jdbc.update(
                sqlCrearRecuperacion, operadorId, tokenHash, tiempo(generadaEn), tiempo(venceEn),
                tiempo(intentoIniciadoEn)) == 1;
    }

    @Override
    public boolean consumirRecuperacion(UUID operadorId, String tokenHash, Instant ahora) {
        return jdbc.update(sqlConsumirRecuperacion, tiempo(ahora), operadorId, tokenHash, tiempo(ahora)) == 1;
    }

    @Override
    public boolean actualizarContrasena(UUID operadorId, long revisionEsperada,
                                        String hashContrasena, Instant ahora) {
        return jdbc.update(sqlActualizarContrasena, hashContrasena, tiempo(ahora), operadorId, revisionEsperada) == 1;
    }

    @Override
    public void invalidarInvitacion(UUID operadorId, Instant ahora) {
        jdbc.update(sqlInvalidarInvitacion, tiempo(ahora), operadorId);
    }

    @Override
    public void invalidarRecuperacion(UUID operadorId, Instant ahora) {
        jdbc.update(sqlInvalidarRecuperacion, tiempo(ahora), operadorId);
    }

    @Override
    public boolean actualizarEstadoInvitacion(UUID operadorId, String tokenHash, EstadoEnvioInvitacion estado) {
        return actualizarEstadoToken("invitacion_operador", operadorId, tokenHash, estado);
    }

    @Override
    public boolean actualizarEstadoRecuperacion(UUID operadorId, String tokenHash, EstadoEnvioInvitacion estado) {
        return actualizarEstadoToken("recuperacion_contrasena_operador", operadorId, tokenHash, estado);
    }

    private boolean actualizarEstadoToken(
            String tabla, UUID operadorId, String tokenHash, EstadoEnvioInvitacion estado) {
        List<Boolean> cambios = jdbc.query("""
                WITH actualizada AS (
                    UPDATE %s SET estado_envio = ?
                    WHERE operador_id = ? AND token_hash = ? AND estado_envio = 'ENVIANDO'
                      AND consumido_en IS NULL
                    RETURNING estado_envio, consumido_en, vence_en
                )
                SELECT estado_envio, consumido_en, vence_en, CURRENT_TIMESTAMP AS ahora FROM actualizada
                """.formatted(tabla), (rs, fila) -> {
            EstadoEnvioInvitacion actual = EstadoEnvioInvitacion.valueOf(rs.getString("estado_envio"));
            Instant consumido = instante(rs, "consumido_en");
            Instant vence = instante(rs, "vence_en");
            Instant ahora = instante(rs, "ahora");
            return !estadoVisible(EstadoEnvioInvitacion.ENVIANDO, consumido, vence, ahora)
                    .equals(estadoVisible(actual, consumido, vence, ahora));
        }, estado.name(), operadorId, tokenHash);
        return !cambios.isEmpty() && cambios.getFirst();
    }

    private static String estadoVisible(
            EstadoEnvioInvitacion estado, Instant consumidoEn, Instant venceEn, Instant ahora) {
        if (consumidoEn != null) {
            return "CONSUMIDA";
        }
        return !ahora.isBefore(venceEn) ? "EXPIRADA" : estado.name();
    }

    @Override
    public void actualizarEstadoAccion(
            UUID operadorId, String operacion, String claveHash, EstadoEnvioInvitacion estado) {
        jdbc.update(sqlActualizarEstadoAccion, estado.name(), operadorId, operacion, claveHash);
    }

    private static InvitacionOperadorPersistida mapearInvitacion(ResultSet rs, int fila) throws SQLException {
        return new InvitacionOperadorPersistida(
                rs.getObject("operador_id", UUID.class), rs.getString("token_hash"),
                instante(rs, "generado_en"), instante(rs, "vence_en"), instante(rs, "consumido_en"),
                EstadoEnvioInvitacion.valueOf(rs.getString("estado_envio")), instante(rs, "intento_iniciado_en"));
    }

    private static RecuperacionContrasenaOperadorPersistida mapearRecuperacion(ResultSet rs, int fila)
            throws SQLException {
        return new RecuperacionContrasenaOperadorPersistida(
                rs.getObject("operador_id", UUID.class), rs.getString("token_hash"),
                instante(rs, "generado_en"), instante(rs, "vence_en"), instante(rs, "consumido_en"),
                EstadoEnvioInvitacion.valueOf(rs.getString("estado_envio")), instante(rs, "intento_iniciado_en"));
    }

    private static AccionOperadorPersistida mapearAccion(ResultSet rs, int fila) throws SQLException {
        return new AccionOperadorPersistida(
                rs.getString("operacion"), instante(rs, "creada_en"),
                EstadoEnvioInvitacion.valueOf(rs.getString("estado_envio")),
                rs.getObject("revision_acceso", Long.class), instante(rs, "vence_en"));
    }

    private static Instant instante(ResultSet rs, String columna) throws SQLException {
        Timestamp valor = rs.getTimestamp(columna);
        return valor == null ? null : valor.toInstant();
    }

    private static Timestamp tiempo(Instant instante) {
        return instante == null ? null : Timestamp.from(instante);
    }
}
