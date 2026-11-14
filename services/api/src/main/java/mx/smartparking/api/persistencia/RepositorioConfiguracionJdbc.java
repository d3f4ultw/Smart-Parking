package mx.smartparking.api.persistencia;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.configuracion.DatosConfiguracion;
import mx.smartparking.api.configuracion.EstadoConfiguracion;
import mx.smartparking.api.configuracion.HorarioConfiguracion;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.ModoHorario;
import mx.smartparking.api.configuracion.TipoEstacionamiento;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/** Consulta y guarda la configuración en el único registro destinado al estacionamiento. */
@Repository
public class RepositorioConfiguracionJdbc implements RepositorioConfiguracion {

    private static final RowMapper<ConfiguracionPersistida> MAPEADOR = RepositorioConfiguracionJdbc::mapear;

    private final String sqlConsultarConfiguracion;
    private final String sqlBloquearConfiguracion;
    private final String sqlConfigurarInicial;
    private final String sqlRenombrar;
    private final String sqlActualizarDatosEstacionamiento;
    private final String sqlIniciarTransferencia;
    private final String sqlReemitirGrant;
    private final String sqlCompletarTransferencia;
    private final JdbcTemplate jdbcTemplate;

    public RepositorioConfiguracionJdbc(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
        this.sqlConsultarConfiguracion = CargadorSql.cargar("configuracion/consultar.sql");
        this.sqlBloquearConfiguracion = CargadorSql.cargar("configuracion/bloquear.sql");
        this.sqlConfigurarInicial = CargadorSql.cargar("configuracion/configurar_inicial.sql");
        this.sqlRenombrar = CargadorSql.cargar("configuracion/renombrar.sql");
        this.sqlActualizarDatosEstacionamiento =
                CargadorSql.cargar("configuracion/actualizar_datos_estacionamiento.sql");
        this.sqlIniciarTransferencia = CargadorSql.cargar("configuracion/iniciar_transferencia.sql");
        this.sqlReemitirGrant = CargadorSql.cargar("configuracion/reemitir_grant.sql");
        this.sqlCompletarTransferencia = CargadorSql.cargar("configuracion/completar_transferencia.sql");
    }

    @Override
    public ConfiguracionPersistida obtener() {
        try {
            return jdbcTemplate.queryForObject(sqlConsultarConfiguracion, MAPEADOR);
        } catch (EmptyResultDataAccessException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.SERVICE_UNAVAILABLE,
                    "No pudimos cargar la información en este momento. Inténtalo más tarde.");
        }
    }

    @Override
    public ConfiguracionPersistida bloquear() {
        try {
            return jdbcTemplate.queryForObject(sqlBloquearConfiguracion, MAPEADOR);
        } catch (EmptyResultDataAccessException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.SERVICE_UNAVAILABLE,
                    "No pudimos cargar la información en este momento. Inténtalo más tarde.");
        }
    }

    @Override
    public Optional<ConfiguracionPersistida> buscar() {
        List<ConfiguracionPersistida> resultados = jdbcTemplate.query(sqlConsultarConfiguracion, MAPEADOR);
        return resultados.stream().findFirst();
    }

    @Override
    public void configurarInicial(
            DatosConfiguracion datos,
            String hashAdministrativa,
            UUID estacionamientoId,
            UUID duenoCuentaId,
            long revision,
            long revisionPropietario,
            UUID operacionId,
            String hashClaveIdempotencia) {
        int filas = jdbcTemplate.update(sqlConfigurarInicial,
                revision,
                revisionPropietario,
                estacionamientoId,
                duenoCuentaId,
                hashAdministrativa,
                datos.nombreEstacionamiento(),
                datos.tipoEstacionamiento().name(),
                datos.horario().modo().name(),
                datos.horario().zonaHoraria(),
                datos.horario().horaApertura(),
                datos.horario().horaCierre(),
                operacionId,
                hashClaveIdempotencia);
        verificarUnaFila(filas);
    }

    @Override
    public void renombrar(String nombre, long revision, UUID operacionId, String hashClaveIdempotencia) {
        int filas = jdbcTemplate.update(sqlRenombrar, nombre, revision, operacionId, hashClaveIdempotencia);
        verificarUnaFila(filas);
    }

    @Override
    public void actualizarDatosEstacionamiento(
            TipoEstacionamiento tipo,
            HorarioConfiguracion horario,
            long revision,
            UUID operacionId,
            String hashClaveIdempotencia) {
        int filas = jdbcTemplate.update(sqlActualizarDatosEstacionamiento,
                tipo.name(),
                horario.modo().name(),
                horario.zonaHoraria(),
                horario.horaApertura(),
                horario.horaCierre(),
                revision,
                operacionId,
                hashClaveIdempotencia);
        verificarUnaFila(filas);
    }

    @Override
    public void iniciarTransferencia(
            UUID transferId,
            String hashGrant,
            Instant venceEn,
            String hashRecuperacion,
            long revision,
            long revisionPropietario,
            UUID operacionId,
            String hashClaveIdempotencia) {
        int filas = jdbcTemplate.update(sqlIniciarTransferencia,
                revision,
                revisionPropietario,
                transferId,
                hashGrant,
                Timestamp.from(venceEn),
                hashRecuperacion,
                operacionId,
                hashClaveIdempotencia);
        verificarUnaFila(filas);
    }

    @Override
    public void reemitirGrant(String hashGrant, Instant venceEn, long revision) {
        int filas = jdbcTemplate.update(sqlReemitirGrant, hashGrant, Timestamp.from(venceEn), revision);
        verificarUnaFila(filas);
    }

    @Override
    public void completarTransferencia(
            DatosConfiguracion datos,
            String hashAdministrativa,
            UUID duenoCuentaId,
            long revision,
            long revisionPropietario,
            UUID operacionId,
            String hashClaveIdempotencia) {
        int filas = jdbcTemplate.update(sqlCompletarTransferencia,
                revision,
                revisionPropietario,
                duenoCuentaId,
                hashAdministrativa,
                datos.nombreEstacionamiento(),
                datos.tipoEstacionamiento().name(),
                datos.horario().modo().name(),
                datos.horario().zonaHoraria(),
                datos.horario().horaApertura(),
                datos.horario().horaCierre(),
                operacionId,
                hashClaveIdempotencia);
        verificarUnaFila(filas);
    }

    @Override
    public void actualizarEstadoAviso(UUID operacionId, TipoAviso tipo, String estado) {
        String columna = switch (tipo) {
            case TRANSFERENCIA -> "estado_aviso_transferencia";
            case BIENVENIDA -> "estado_aviso_bienvenida";
        };
        jdbcTemplate.update("UPDATE configuracion_estacionamiento SET " + columna
                + " = ? WHERE id = 1 AND ultima_operacion_id = ? AND " + columna + " = 'RESERVADO'",
                estado,
                operacionId);
    }

    private static ConfiguracionPersistida mapear(ResultSet rs, int fila) throws SQLException {
        return new ConfiguracionPersistida(
                EstadoConfiguracion.valueOf(rs.getString("estado")),
                rs.getLong("revision"),
                rs.getLong("revision_propietario"),
                rs.getObject("estacionamiento_id", UUID.class),
                rs.getString("propietario_nombres"),
                rs.getString("propietario_primer_apellido"),
                rs.getString("propietario_segundo_apellido"),
                rs.getString("correo_propietario"),
                rs.getString("hash_contrasena_acceso"),
                rs.getString("hash_contrasena_administrativa"),
                rs.getString("nombre_estacionamiento"),
                enumSiExiste(TipoEstacionamiento.class, rs.getString("tipo_estacionamiento")),
                enumSiExiste(ModoHorario.class, rs.getString("modo_horario")),
                rs.getString("zona_horaria"),
                hora(rs, "hora_apertura"),
                hora(rs, "hora_cierre"),
                rs.getObject("transfer_id", UUID.class),
                rs.getString("hash_grant_transferencia"),
                instante(rs, "grant_vence_en"),
                rs.getString("hash_recuperacion_transferencia"),
                rs.getString("estado_aviso_transferencia"),
                rs.getString("estado_aviso_bienvenida"),
                rs.getObject("ultima_operacion_id", UUID.class),
                rs.getString("ultima_clave_idempotencia_hash"));
    }

    private static LocalTime hora(ResultSet rs, String columna) throws SQLException {
        return rs.getObject(columna, LocalTime.class);
    }

    private static Instant instante(ResultSet rs, String columna) throws SQLException {
        Timestamp timestamp = rs.getTimestamp(columna);
        return timestamp == null ? null : timestamp.toInstant();
    }

    private static <T extends Enum<T>> T enumSiExiste(Class<T> tipo, String valor) {
        return valor == null ? null : Enum.valueOf(tipo, valor);
    }

    private static void verificarUnaFila(int filas) {
        if (filas != 1) {
            throw new ErrorConfiguracion(HttpStatus.CONFLICT,
                    "La información cambió. Actualiza la pantalla antes de continuar.");
        }
    }
}
