package mx.smartparking.api.rfid1.persistencia;

import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.CapturaRfid1Persistida;
import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.DestinoRfid1Persistido;
import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.ResultadoConfirmacionRfid1;
import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.VistaPreviaRfid1Persistida;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.configuracion.TipoEstacionamiento;
import mx.smartparking.api.persistencia.CargadorSql;
import mx.smartparking.api.rfid1.PoliticaModalidadRfid1;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * Lee por un momento el número de tarjeta y confirma su asociación procurando que otros cambios no
 * interfieran.
 */
@Repository
public class RepositorioConfirmacionRfid1Jdbc {

    private static final String CAPTURA_NO_VIGENTE = "CAPTURA_NO_VIGENTE";
    private static final String CAPTURA_NO_ENCONTRADA = "CAPTURA_NO_ENCONTRADA";
    private static final String TARJETA_YA_REGISTRADA = "TARJETA_YA_REGISTRADA";
    private static final String PERSONA_CON_TARJETA = "PERSONA_CON_TARJETA";
    private static final String CLAVE_EN_CONFLICTO = "CLAVE_IDEMPOTENCIA_EN_CONFLICTO";
    private final JdbcTemplate jdbc;
    private final ResolutorDestinoRfid1 resolutorDestino;
    private final String sqlBloquearCaptura;
    private final String sqlBuscarVistaTemporal;
    private final String sqlCuentaVigente;
    private final String sqlBloquearModalidadActual;
    private final String sqlDestinoTieneTarjetaCliente;
    private final String sqlDestinoTieneTarjetaEmpleado;
    private final String sqlUidYaAsociado;
    private final String sqlInsertarAsociacion;
    private final String sqlCompletarCaptura;
    private final String sqlTerminalizarCaptura;

    public RepositorioConfirmacionRfid1Jdbc(JdbcTemplate jdbc, ResolutorDestinoRfid1 resolutorDestino) {
        this.jdbc = jdbc;
        this.resolutorDestino = resolutorDestino;
        this.sqlBloquearCaptura = CargadorSql.cargar("rfid1/bloquear_captura.sql");
        this.sqlBuscarVistaTemporal = CargadorSql.cargar("rfid1/buscar_vista_temporal.sql");
        this.sqlCuentaVigente = CargadorSql.cargar("rfid1/cuenta_vigente.sql");
        this.sqlBloquearModalidadActual = CargadorSql.cargar("rfid1/bloquear_modalidad_actual.sql");
        this.sqlDestinoTieneTarjetaCliente = CargadorSql.cargar("rfid1/destino_tiene_tarjeta_cliente.sql");
        this.sqlDestinoTieneTarjetaEmpleado = CargadorSql.cargar("rfid1/destino_tiene_tarjeta_empleado.sql");
        this.sqlUidYaAsociado = CargadorSql.cargar("rfid1/uid_ya_asociado.sql");
        this.sqlInsertarAsociacion = CargadorSql.cargar("rfid1/insertar_asociacion.sql");
        this.sqlCompletarCaptura = CargadorSql.cargar("rfid1/completar_captura_confirmacion.sql");
        this.sqlTerminalizarCaptura = CargadorSql.cargar("rfid1/terminalizar_captura_confirmacion.sql");
    }

    public Optional<VistaPreviaRfid1Persistida> consultarVistaPrevia(
            String capturaId,
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion,
            Instant ahora) {
        CapturaRfid1Persistida captura = bloquearCaptura(capturaId);
        if (!pertenece(captura, propietarioId, revisionAcceso, revisionPropietario, huellaSesion)
                || !cuentaVigente(captura)) {
            return Optional.empty();
        }
        if (!"VISTA_PREVIA".equals(captura.estado())) {
            return Optional.empty();
        }
        if (captura.confirmacionVenceEn() == null || !captura.confirmacionVenceEn().isAfter(ahora)) {
            terminalizar(capturaId, "EXPIRADA", null, ahora);
            return Optional.empty();
        }
        VistaTemporal vista = buscarVistaTemporal(capturaId).orElse(null);
        if (vista == null || !vista.huellaUid().equals(captura.huellaUid())) {
            terminalizar(capturaId, "CANCELADA", CAPTURA_NO_VIGENTE, ahora);
            return Optional.empty();
        }
        return Optional.of(new VistaPreviaRfid1Persistida(
                vista.uidCanonico(), vista.previsualizadaEn(), vista.confirmacionVenceEn()));
    }

    public ResultadoConfirmacionRfid1 confirmarCaptura(
            String capturaId,
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion,
            String hashClaveConfirmacion,
            Instant ahora) {
        CapturaRfid1Persistida captura = bloquearCaptura(capturaId);
        if (!pertenece(captura, propietarioId, revisionAcceso, revisionPropietario, huellaSesion)
                || !cuentaVigente(captura)) {
            return error(null, CAPTURA_NO_ENCONTRADA);
        }
        if (hashClaveConfirmacion != null && hashClaveConfirmacion.equals(captura.hashClaveConfirmacion())) {
            return replay(captura);
        }
        if ("COMPLETADA".equals(captura.estado())) {
            return error(captura.estado(), CLAVE_EN_CONFLICTO);
        }
        if (!"VISTA_PREVIA".equals(captura.estado())) {
            return error(captura.estado(), CAPTURA_NO_VIGENTE);
        }
        if (captura.confirmacionVenceEn() == null || !captura.confirmacionVenceEn().isAfter(ahora)) {
            terminalizar(capturaId, "EXPIRADA", null, ahora);
            return error("EXPIRADA", CAPTURA_NO_VIGENTE);
        }

        VistaTemporal vista = buscarVistaTemporal(capturaId).orElse(null);
        if (vista == null || !vista.huellaUid().equals(captura.huellaUid())) {
            terminalizar(capturaId, "CANCELADA", CAPTURA_NO_VIGENTE, ahora);
            return error("CANCELADA", CAPTURA_NO_VIGENTE);
        }
        TipoEstacionamiento modalidad = bloquearModalidadActual();
        if (!PoliticaModalidadRfid1.permite(modalidad, captura.tipoEntidad())) {
            terminalizar(capturaId, "CANCELADA", CAPTURA_NO_VIGENTE, ahora);
            return error("CANCELADA", CAPTURA_NO_VIGENTE);
        }
        DestinoRfid1Persistido destino = resolutorDestino.resolver(
                captura.tipoEntidad(), captura.codigoPersona()).filter(valor ->
                valor.clienteId() == null
                        ? valor.empleadoId().equals(captura.empleadoId())
                        : valor.clienteId().equals(captura.clienteId())).orElse(null);
        if (destino == null || !destino.activo()) {
            terminalizar(capturaId, "CANCELADA", CAPTURA_NO_VIGENTE, ahora);
            return error("CANCELADA", CAPTURA_NO_VIGENTE);
        }
        if (destino.sinMembresia()) {
            terminalizar(capturaId, "CANCELADA", "CLIENTE_SIN_MEMBRESIA", ahora);
            return error("CANCELADA", "CLIENTE_SIN_MEMBRESIA");
        }
        if (destinoTieneTarjetaActiva(destino)) {
            guardarError(capturaId, hashClaveConfirmacion, PERSONA_CON_TARJETA, ahora, true);
            return error("CANCELADA", PERSONA_CON_TARJETA);
        }
        if (uidYaAsociado(vista.uidCanonico())) {
            guardarError(capturaId, hashClaveConfirmacion, TARJETA_YA_REGISTRADA, ahora, false);
            return error("ESCANEANDO", TARJETA_YA_REGISTRADA);
        }

        Long asociacionId = insertarAsociacion(captura, vista.uidCanonico(), ahora);
        if (asociacionId == null) {
            String codigo = uidYaAsociado(vista.uidCanonico()) ? TARJETA_YA_REGISTRADA : PERSONA_CON_TARJETA;
            boolean terminar = PERSONA_CON_TARJETA.equals(codigo);
            guardarError(capturaId, hashClaveConfirmacion, codigo, ahora, terminar);
            return error(terminar ? "CANCELADA" : "ESCANEANDO", codigo);
        }
        completar(capturaId, hashClaveConfirmacion, asociacionId, ahora);
        return new ResultadoConfirmacionRfid1("COMPLETADA", asociacionId, null, false);
    }

    private CapturaRfid1Persistida bloquearCaptura(String capturaId) {
        return jdbc.query(sqlBloquearCaptura,
                RepositorioRfid1Jdbc::mapearCaptura, capturaId).stream().findFirst().orElse(null);
    }

    private Optional<VistaTemporal> buscarVistaTemporal(String capturaId) {
        return jdbc.query(sqlBuscarVistaTemporal, (rs, fila) -> new VistaTemporal(
                rs.getString("uid_canonico"), rs.getString("huella_uid"),
                instante(rs, "previsualizada_en"), instante(rs, "confirmacion_vence_en")), capturaId)
                .stream().findFirst();
    }

    private boolean cuentaVigente(CapturaRfid1Persistida captura) {
        if (captura == null) {
            return false;
        }
        List<UUID> cuentas = jdbc.query(sqlCuentaVigente, (rs, fila) -> rs.getObject("id", UUID.class),
                captura.propietarioId(), captura.revisionAcceso(), captura.revisionPropietario());
        return !cuentas.isEmpty();
    }

    private TipoEstacionamiento bloquearModalidadActual() {
        return jdbc.query(sqlBloquearModalidadActual,
                (rs, fila) -> TipoEstacionamiento.valueOf(rs.getString("tipo_estacionamiento")))
                .stream().findFirst().orElse(null);
    }

    private static boolean pertenece(
            CapturaRfid1Persistida captura,
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion) {
        return captura != null && propietarioId.equals(captura.propietarioId())
                && revisionAcceso == captura.revisionAcceso()
                && revisionPropietario == captura.revisionPropietario()
                && huellaSesion != null && huellaSesion.equals(captura.huellaSesion());
    }

    private boolean destinoTieneTarjetaActiva(DestinoRfid1Persistido destino) {
        String sql = destino.clienteId() != null
                ? sqlDestinoTieneTarjetaCliente
                : sqlDestinoTieneTarjetaEmpleado;
        Object id = destino.clienteId() != null ? destino.clienteId() : destino.empleadoId();
        Boolean existe = jdbc.queryForObject(sql, Boolean.class, id);
        return Boolean.TRUE.equals(existe);
    }

    private boolean uidYaAsociado(String uid) {
        Boolean existe = jdbc.queryForObject(sqlUidYaAsociado, Boolean.class, uid);
        return Boolean.TRUE.equals(existe);
    }

    private Long insertarAsociacion(CapturaRfid1Persistida captura, String uid, Instant ahora) {
        List<Long> ids = jdbc.query(sqlInsertarAsociacion, (rs, fila) -> rs.getLong("asociacion_id"), uid,
                captura.clienteId(), captura.empleadoId(), Timestamp.from(ahora));
        return ids.stream().findFirst().orElse(null);
    }

    private void guardarError(String capturaId, String hashClave, String codigo, Instant ahora, boolean terminar) {
        Timestamp tiempo = Timestamp.from(ahora);
        String estado = terminar ? "CANCELADA" : "ESCANEANDO";
        String errorCaptura = terminar ? CAPTURA_NO_VIGENTE : codigo;
        String fin = terminar ? ", terminada_en = ?" : "";
        String sql = """
                UPDATE captura_rfid1
                SET estado = ?, resultado = NULL, codigo_error = ?, actualizada_en = ?%s,
                    hash_clave_confirmacion = ?, codigo_confirmacion = ?, asociacion_confirmada_id = NULL
                WHERE captura_id = ? AND estado = 'VISTA_PREVIA'
                """.formatted(fin);
        Object[] valores;
        if (terminar) {
            valores = new Object[] {estado, errorCaptura, tiempo, tiempo, hashClave, codigo, capturaId};
        } else {
            valores = new Object[] {estado, errorCaptura, tiempo, hashClave, codigo, capturaId};
        }
        exigirUnaFila(jdbc.update(sql, valores));
    }

    private void completar(String capturaId, String hashClave, long asociacionId, Instant ahora) {
        Timestamp tiempo = Timestamp.from(ahora);
        exigirUnaFila(jdbc.update(sqlCompletarCaptura, tiempo, tiempo, hashClave, asociacionId, capturaId));
    }

    private void terminalizar(String capturaId, String estado, String codigoError, Instant ahora) {
        Timestamp tiempo = Timestamp.from(ahora);
        exigirUnaFila(jdbc.update(sqlTerminalizarCaptura, estado, codigoError, tiempo, tiempo, capturaId));
    }

    private static ResultadoConfirmacionRfid1 replay(CapturaRfid1Persistida captura) {
        if (captura.asociacionConfirmadaId() != null) {
            return new ResultadoConfirmacionRfid1("COMPLETADA", captura.asociacionConfirmadaId(), null, true);
        }
        String codigo = captura.codigoConfirmacion() == null ? CAPTURA_NO_VIGENTE : captura.codigoConfirmacion();
        return new ResultadoConfirmacionRfid1(captura.estado(), null, codigo, true);
    }

    private static ResultadoConfirmacionRfid1 error(String estado, String codigo) {
        return new ResultadoConfirmacionRfid1(estado, null, codigo, false);
    }

    private static void exigirUnaFila(int filas) {
        if (filas != 1) {
            throw new DataAccessResourceFailureException("No se pudo aplicar la confirmación RFID.");
        }
    }

    private static Instant instante(ResultSet rs, String columna) throws SQLException {
        Timestamp marca = rs.getTimestamp(columna);
        return marca == null ? null : marca.toInstant();
    }

    record VistaTemporal(String uidCanonico, String huellaUid, Instant previsualizadaEn,
            Instant confirmacionVenceEn) {
    }
}
