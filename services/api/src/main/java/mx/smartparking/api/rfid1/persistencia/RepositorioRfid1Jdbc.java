package mx.smartparking.api.rfid1.persistencia;

import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.CapturaRfid1Persistida;
import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.DestinoRfid1Persistido;
import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.NuevaCapturaRfid1;
import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.ResultadoConfirmacionRfid1;
import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.ResultadoEstadoCaptura;
import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.ResultadoLecturaRfid1;
import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.VistaPreviaRfid1Persistida;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import mx.smartparking.api.persistencia.CargadorSql;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/** Consulta las lecturas de tarjetas y encarga sus cambios a los componentes correspondientes. */
@Repository
public class RepositorioRfid1Jdbc implements RepositorioRfid1 {

    private static final String CONDICION_DUENO_VIGENTE = """
            EXISTS (
                SELECT 1
                FROM cuenta cuenta_actual
                JOIN configuracion_estacionamiento configuracion_actual ON configuracion_actual.id = 1
                WHERE cuenta_actual.id = captura.propietario_cuenta_id
                  AND cuenta_actual.estado = 'ACTIVA'
                  AND cuenta_actual.revision_acceso = captura.revision_acceso
                  AND configuracion_actual.estado = 'CONFIGURADA'
                  AND (
                      (cuenta_actual.rol = 'DUENO'
                       AND configuracion_actual.dueno_cuenta_id = cuenta_actual.id
                       AND configuracion_actual.revision_propietario = captura.revision_propietario)
                      OR (cuenta_actual.rol = 'OPERADOR' AND EXISTS (
                          SELECT 1 FROM empleado empleado_actual
                          WHERE empleado_actual.id = cuenta_actual.empleado_id
                            AND empleado_actual.estado = 'ACTIVO'))
                  )
            )
            """;
    private static final RowMapper<CapturaRfid1Persistida> MAPA_CAPTURA = RepositorioRfid1Jdbc::mapearCaptura;

    private final JdbcTemplate jdbc;
    private final ResolutorDestinoRfid1 resolutorDestino;
    private final RepositorioTransicionesRfid1Jdbc transiciones;
    private final RepositorioConfirmacionRfid1Jdbc confirmaciones;
    private final String sqlDestinoTieneTarjetaCliente;
    private final String sqlDestinoTieneTarjetaEmpleado;
    private final String sqlBuscarPorIdempotencia;
    private final String sqlInsertarCaptura;

    @Autowired
    public RepositorioRfid1Jdbc(
            JdbcTemplate jdbc,
            ResolutorDestinoRfid1 resolutorDestino,
            RepositorioTransicionesRfid1Jdbc transiciones,
            RepositorioConfirmacionRfid1Jdbc confirmaciones) {
        this.jdbc = jdbc;
        this.resolutorDestino = resolutorDestino;
        this.transiciones = transiciones;
        this.confirmaciones = confirmaciones;
        this.sqlDestinoTieneTarjetaCliente = CargadorSql.cargar("rfid1/destino_tiene_tarjeta_cliente.sql");
        this.sqlDestinoTieneTarjetaEmpleado = CargadorSql.cargar("rfid1/destino_tiene_tarjeta_empleado.sql");
        this.sqlBuscarPorIdempotencia = CargadorSql.cargar("rfid1/buscar_captura_por_idempotencia.sql");
        this.sqlInsertarCaptura = CargadorSql.cargar("rfid1/insertar_captura.sql");
    }

    RepositorioRfid1Jdbc(JdbcTemplate jdbc, ResolutorDestinoRfid1 resolutorDestino) {
        this(jdbc, resolutorDestino, new RepositorioTransicionesRfid1Jdbc(jdbc),
                new RepositorioConfirmacionRfid1Jdbc(jdbc, resolutorDestino));
    }

    @Override
    public int expirarCapturasVencidas(Instant ahora) {
        return transiciones.expirarCapturasVencidas(ahora);
    }

    @Override
    public int purgarCapturasTerminalesAnterioresA(Instant limite) {
        return transiciones.purgarCapturasTerminalesAnterioresA(limite);
    }

    @Override
    public Optional<DestinoRfid1Persistido> resolverDestino(String tipoEntidad, String codigoPersona) {
        return resolutorDestino.resolver(tipoEntidad, codigoPersona);
    }

    @Override
    public boolean destinoTieneTarjeta(DestinoRfid1Persistido destino) {
        String sql = destino.clienteId() != null
                ? sqlDestinoTieneTarjetaCliente
                : sqlDestinoTieneTarjetaEmpleado;
        Object id = destino.clienteId() != null ? destino.clienteId() : destino.empleadoId();
        Boolean existe = jdbc.queryForObject(sql, Boolean.class, id);
        return Boolean.TRUE.equals(existe);
    }

    @Override
    public Optional<CapturaRfid1Persistida> buscarPorIdempotencia(
            UUID propietarioId, String claveHash, String huellaSesion) {
        return consultarCaptura(sqlBuscarPorIdempotencia, propietarioId, claveHash, huellaSesion);
    }

    @Override
    public Optional<CapturaRfid1Persistida> buscarActivaDePropietario(
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion,
            Instant ahora) {
        Timestamp tiempo = Timestamp.from(ahora);
        return consultarCaptura("""
                SELECT * FROM captura_rfid1 AS captura
                WHERE propietario_cuenta_id = ? AND revision_acceso = ? AND revision_propietario = ?
                  AND huella_sesion = ?
                  AND ((estado IN ('PENDIENTE', 'ESCANEANDO') AND vence_en > ?)
                    OR (estado = 'VISTA_PREVIA' AND confirmacion_vence_en > ?))
                  AND %s
                """.formatted(CONDICION_DUENO_VIGENTE),
                propietarioId, revisionAcceso, revisionPropietario, huellaSesion, tiempo, tiempo);
    }

    @Override
    public Optional<CapturaRfid1Persistida> buscarActivaParaDispositivo(Instant ahora) {
        transiciones.expirarCapturasVencidas(ahora);
        Timestamp tiempo = Timestamp.from(ahora);
        return consultarCaptura("""
                SELECT * FROM captura_rfid1 AS captura
                WHERE estado IN ('PENDIENTE', 'ESCANEANDO', 'VISTA_PREVIA') AND huella_sesion IS NOT NULL
                  AND ((estado IN ('PENDIENTE', 'ESCANEANDO') AND vence_en > ?)
                    OR (estado = 'VISTA_PREVIA' AND confirmacion_vence_en > ?))
                  AND %s
                """.formatted(CONDICION_DUENO_VIGENTE), tiempo, tiempo);
    }

    @Override
    public Optional<CapturaRfid1Persistida> buscarPorPropietario(
            String capturaId,
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion) {
        return consultarCaptura("""
                SELECT * FROM captura_rfid1 AS captura
                WHERE captura_id = ? AND propietario_cuenta_id = ?
                  AND revision_acceso = ? AND revision_propietario = ? AND huella_sesion = ?
                  AND %s
                """.formatted(CONDICION_DUENO_VIGENTE),
                capturaId, propietarioId, revisionAcceso, revisionPropietario, huellaSesion);
    }

    private Optional<CapturaRfid1Persistida> consultarCaptura(String sql, Object... parametros) {
        return jdbc.query(sql, MAPA_CAPTURA, parametros).stream().findFirst();
    }

    @Override
    public boolean insertarCaptura(NuevaCapturaRfid1 nueva) {
        return jdbc.update(sqlInsertarCaptura, nueva.capturaId(), nueva.tipoEntidad(), nueva.codigoPersona(), nueva.clienteId(),
                nueva.empleadoId(), nueva.propietarioId(), nueva.revisionAcceso(), nueva.revisionPropietario(),
                nueva.huellaSesion(), nueva.claveIdempotenciaHash(), nueva.huellaSolicitud(),
                Timestamp.from(nueva.creadaEn()), Timestamp.from(nueva.creadaEn()),
                Timestamp.from(nueva.venceEn())) == 1;
    }

    @Override
    public ResultadoEstadoCaptura marcarEscaneando(String capturaId, Instant ahora) {
        return transiciones.marcarEscaneando(capturaId, ahora);
    }

    @Override
    public ResultadoEstadoCaptura cancelar(
            String capturaId,
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion,
            Instant ahora) {
        return transiciones.cancelar(
                capturaId, propietarioId, revisionAcceso, revisionPropietario, huellaSesion, ahora);
    }

    @Override
    public ResultadoLecturaRfid1 completarLectura(
            String capturaId, String requestId, String uidCanonico, String huellaUid, Instant ahora) {
        return transiciones.completarLectura(capturaId, requestId, uidCanonico, huellaUid, ahora);
    }

    @Override
    public Optional<VistaPreviaRfid1Persistida> consultarVistaPrevia(
            String capturaId,
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion,
            Instant ahora) {
        return confirmaciones.consultarVistaPrevia(
                capturaId, propietarioId, revisionAcceso, revisionPropietario, huellaSesion, ahora);
    }

    @Override
    public ResultadoConfirmacionRfid1 confirmarCaptura(
            String capturaId,
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion,
            String hashClaveConfirmacion,
            Instant ahora) {
        return confirmaciones.confirmarCaptura(
                capturaId, propietarioId, revisionAcceso, revisionPropietario,
                huellaSesion, hashClaveConfirmacion, ahora);
    }

    @Override
    public int invalidarPorSesion(String huellaSesion, Instant ahora) {
        return transiciones.invalidarPorSesion(huellaSesion, ahora);
    }

    @Override
    public int invalidarSesionesAusentes(Set<String> huellasActivas, Instant ahora) {
        return transiciones.invalidarSesionesAusentes(huellasActivas, ahora);
    }

    static CapturaRfid1Persistida mapearCaptura(ResultSet rs, int fila) throws SQLException {
        return new CapturaRfid1Persistida(
                limpiarCampoFijo(rs.getString("captura_id")),
                rs.getString("tipo_entidad"),
                rs.getString("codigo_persona"),
                rs.getObject("cliente_id", UUID.class),
                rs.getObject("empleado_id", Long.class),
                rs.getObject("propietario_cuenta_id", UUID.class),
                rs.getLong("revision_acceso"),
                rs.getLong("revision_propietario"),
                limpiarCampoFijo(rs.getString("huella_sesion")),
                limpiarCampoFijo(rs.getString("clave_inicio_hash")),
                limpiarCampoFijo(rs.getString("huella_solicitud")),
                limpiarCampoFijo(rs.getString("request_id")),
                limpiarCampoFijo(rs.getString("huella_uid")),
                rs.getString("estado"),
                rs.getString("resultado"),
                rs.getString("codigo_error"),
                instante(rs, "creada_en"),
                instante(rs, "vence_en"),
                instante(rs, "terminada_en"),
                instante(rs, "previsualizada_en"),
                instante(rs, "confirmacion_vence_en"),
                limpiarCampoFijo(rs.getString("hash_clave_confirmacion")),
                rs.getString("codigo_confirmacion"),
                rs.getObject("asociacion_confirmada_id", Long.class));
    }

    private static String limpiarCampoFijo(String texto) {
        return texto == null ? null : texto.strip();
    }

    private static Instant instante(ResultSet rs, String columna) throws SQLException {
        Timestamp valor = rs.getTimestamp(columna);
        return valor == null ? null : valor.toInstant();
    }
}
