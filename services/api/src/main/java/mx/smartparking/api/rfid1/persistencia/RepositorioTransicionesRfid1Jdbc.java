package mx.smartparking.api.rfid1.persistencia;

import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.CapturaRfid1Persistida;
import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.ResultadoEstadoCaptura;
import static mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.ResultadoLecturaRfid1;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import mx.smartparking.api.persistencia.CargadorSql;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Guarda lecturas y cancelaciones evitando que varios cambios sobre la misma lectura interfieran. */
@Repository
public class RepositorioTransicionesRfid1Jdbc {

    private static final String CAPTURA_NO_VIGENTE = "CAPTURA_NO_VIGENTE";
    private static final String CAPTURA_NO_ENCONTRADA = "CAPTURA_NO_ENCONTRADA";
    private static final String TARJETA_YA_REGISTRADA = "TARJETA_YA_REGISTRADA";
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

    private final JdbcTemplate jdbc;
    private final String sqlPurgarCapturasTerminales;
    private final String sqlMarcarCapturaEscaneando;
    private final String sqlBloquearCaptura;
    private final String sqlCuentaVigente;
    private final String sqlTerminalizarCaptura;
    private final String sqlRegistrarUidRechazado;
    private final String sqlActualizarCapturaVistaPrevia;
    private final String sqlInsertarUidTemporal;
    private final String sqlUidYaAsociado;

    public RepositorioTransicionesRfid1Jdbc(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
        this.sqlPurgarCapturasTerminales = CargadorSql.cargar("rfid1/purgar_capturas_terminales.sql");
        this.sqlMarcarCapturaEscaneando = CargadorSql.cargar("rfid1/marcar_captura_escaneando.sql");
        this.sqlBloquearCaptura = CargadorSql.cargar("rfid1/bloquear_captura.sql");
        this.sqlCuentaVigente = CargadorSql.cargar("rfid1/cuenta_vigente.sql");
        this.sqlTerminalizarCaptura = CargadorSql.cargar("rfid1/terminalizar_captura_transicion.sql");
        this.sqlRegistrarUidRechazado = CargadorSql.cargar("rfid1/registrar_uid_rechazado.sql");
        this.sqlActualizarCapturaVistaPrevia = CargadorSql.cargar("rfid1/actualizar_captura_vista_previa.sql");
        this.sqlInsertarUidTemporal = CargadorSql.cargar("rfid1/insertar_uid_temporal.sql");
        this.sqlUidYaAsociado = CargadorSql.cargar("rfid1/uid_ya_asociado.sql");
    }

    public int expirarCapturasVencidas(Instant ahora) {
        List<CapturaRfid1Persistida> capturas = jdbc.query("""
                SELECT * FROM captura_rfid1
                WHERE estado IN ('PENDIENTE', 'ESCANEANDO', 'VISTA_PREVIA')
                FOR UPDATE
                """, RepositorioRfid1Jdbc::mapearCaptura);
        int cambios = 0;
        for (CapturaRfid1Persistida captura : capturas) {
            if (!cuentaVigente(captura)) {
                terminalizar(captura.capturaId(), "CANCELADA", CAPTURA_NO_VIGENTE, ahora);
                cambios++;
            } else if (vigenciaVencida(captura, ahora)) {
                terminalizar(captura.capturaId(), "EXPIRADA", null, ahora);
                cambios++;
            }
        }
        return cambios;
    }

    public int purgarCapturasTerminalesAnterioresA(Instant limite) {
        return jdbc.update(sqlPurgarCapturasTerminales, Timestamp.from(limite));
    }

    public ResultadoEstadoCaptura marcarEscaneando(String capturaId, Instant ahora) {
        expirarCapturasVencidas(ahora);
        CapturaRfid1Persistida captura = bloquearCaptura(capturaId);
        if (captura == null) {
            return new ResultadoEstadoCaptura(null, CAPTURA_NO_VIGENTE);
        }
        if ("ESCANEANDO".equals(captura.estado()) && cuentaVigente(captura)) {
            return new ResultadoEstadoCaptura("ESCANEANDO", null);
        }
        if (!"PENDIENTE".equals(captura.estado())) {
            return new ResultadoEstadoCaptura(captura.estado(), CAPTURA_NO_VIGENTE);
        }
        if (!cuentaVigente(captura) || captura.huellaSesion() == null) {
            terminalizar(capturaId, "CANCELADA", CAPTURA_NO_VIGENTE, ahora);
            return new ResultadoEstadoCaptura("CANCELADA", CAPTURA_NO_VIGENTE);
        }
        int filas = jdbc.update(sqlMarcarCapturaEscaneando,
                Timestamp.from(ahora), capturaId, Timestamp.from(ahora));
        return filas == 1
                ? new ResultadoEstadoCaptura("ESCANEANDO", null)
                : new ResultadoEstadoCaptura("EXPIRADA", CAPTURA_NO_VIGENTE);
    }

    public ResultadoEstadoCaptura cancelar(
            String capturaId,
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion,
            Instant ahora) {
        expirarCapturasVencidas(ahora);
        CapturaRfid1Persistida captura = bloquearCaptura(capturaId);
        if (!pertenece(captura, propietarioId, revisionAcceso, revisionPropietario, huellaSesion)
                || !cuentaVigente(captura)) {
            return new ResultadoEstadoCaptura(null, CAPTURA_NO_ENCONTRADA);
        }
        if ("CANCELADA".equals(captura.estado())) {
            return new ResultadoEstadoCaptura("CANCELADA", null);
        }
        if (!estaActiva(captura)) {
            return new ResultadoEstadoCaptura(captura.estado(), CAPTURA_NO_VIGENTE);
        }
        terminalizar(capturaId, "CANCELADA", null, ahora);
        return new ResultadoEstadoCaptura("CANCELADA", null);
    }

    public ResultadoLecturaRfid1 completarLectura(
            String capturaId, String requestId, String uidCanonico, String huellaUid, Instant ahora) {
        expirarCapturasVencidas(ahora);
        CapturaRfid1Persistida captura = bloquearCaptura(capturaId);
        if (captura == null) {
            return resultadoNoVigente();
        }
        if (captura.requestId() != null && captura.requestId().equals(requestId)
                && huellaUid.equals(captura.huellaUid())) {
            return new ResultadoLecturaRfid1(
                    captura.estado(), captura.resultado(), captura.codigoError(), true);
        }
        if (!("PENDIENTE".equals(captura.estado()) || "ESCANEANDO".equals(captura.estado()))) {
            return resultadoNoVigente();
        }
        if (!cuentaVigente(captura) || captura.huellaSesion() == null) {
            terminalizar(capturaId, "CANCELADA", CAPTURA_NO_VIGENTE, ahora);
            return new ResultadoLecturaRfid1("CANCELADA", null, CAPTURA_NO_VIGENTE, false);
        }
        if (uidYaAsociado(uidCanonico)) {
            registrarUidRechazado(capturaId, requestId, huellaUid, ahora);
            return new ResultadoLecturaRfid1("ESCANEANDO", null, TARJETA_YA_REGISTRADA, false);
        }

        Instant confirmacionVence = ahora.plusSeconds(300);
        actualizarVistaPrevia(capturaId, requestId, huellaUid, ahora, confirmacionVence);
        insertarUidTemporal(capturaId, uidCanonico, huellaUid, ahora, confirmacionVence);
        return new ResultadoLecturaRfid1("VISTA_PREVIA", "PREVIEW_READY", null, false);
    }

    public int invalidarPorSesion(String huellaSesion, Instant ahora) {
        List<CapturaRfid1Persistida> capturas = jdbc.query("""
                SELECT * FROM captura_rfid1
                WHERE huella_sesion = ? AND estado IN ('PENDIENTE', 'ESCANEANDO', 'VISTA_PREVIA')
                FOR UPDATE
                """, RepositorioRfid1Jdbc::mapearCaptura, huellaSesion);
        capturas.forEach(captura -> terminalizar(
                captura.capturaId(), "CANCELADA", CAPTURA_NO_VIGENTE, ahora));
        return capturas.size();
    }

    public int invalidarSesionesAusentes(Set<String> huellasActivas, Instant ahora) {
        List<CapturaRfid1Persistida> capturas = jdbc.query("""
                SELECT * FROM captura_rfid1
                WHERE estado IN ('PENDIENTE', 'ESCANEANDO', 'VISTA_PREVIA') AND creada_en < ?
                FOR UPDATE
                """, RepositorioRfid1Jdbc::mapearCaptura, Timestamp.from(ahora));
        int invalidas = 0;
        for (CapturaRfid1Persistida captura : capturas) {
            if (captura.huellaSesion() == null || huellasActivas == null
                    || !huellasActivas.contains(captura.huellaSesion()) || !cuentaVigente(captura)) {
                terminalizar(captura.capturaId(), "CANCELADA", CAPTURA_NO_VIGENTE, ahora);
                invalidas++;
            }
        }
        return invalidas;
    }

    private CapturaRfid1Persistida bloquearCaptura(String capturaId) {
        return jdbc.query(sqlBloquearCaptura,
                RepositorioRfid1Jdbc::mapearCaptura, capturaId).stream().findFirst().orElse(null);
    }

    private boolean cuentaVigente(CapturaRfid1Persistida captura) {
        if (captura == null) {
            return false;
        }
        List<UUID> cuentas = jdbc.query(sqlCuentaVigente, (rs, fila) -> rs.getObject("id", UUID.class),
                captura.propietarioId(), captura.revisionAcceso(), captura.revisionPropietario());
        return !cuentas.isEmpty();
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

    private void terminalizar(String capturaId, String estado, String codigoError, Instant ahora) {
        Timestamp tiempo = Timestamp.from(ahora);
        exigirUnaFila(jdbc.update(sqlTerminalizarCaptura, estado, codigoError, tiempo, tiempo, capturaId));
    }

    private void registrarUidRechazado(String capturaId, String requestId, String huellaUid, Instant ahora) {
        exigirUnaFila(jdbc.update(sqlRegistrarUidRechazado,
                requestId, huellaUid, Timestamp.from(ahora), capturaId));
    }

    private void actualizarVistaPrevia(
            String capturaId, String requestId, String huellaUid, Instant ahora, Instant confirmacionVence) {
        exigirUnaFila(jdbc.update(sqlActualizarCapturaVistaPrevia,
                requestId, huellaUid, Timestamp.from(ahora), Timestamp.from(ahora),
                Timestamp.from(confirmacionVence), capturaId, Timestamp.from(ahora)));
    }

    private void insertarUidTemporal(
            String capturaId, String uid, String huellaUid, Instant ahora, Instant confirmacionVence) {
        exigirUnaFila(jdbc.update(sqlInsertarUidTemporal,
                capturaId, uid, huellaUid, Timestamp.from(ahora), Timestamp.from(confirmacionVence)));
    }

    private boolean uidYaAsociado(String uid) {
        Boolean existe = jdbc.queryForObject(sqlUidYaAsociado, Boolean.class, uid);
        return Boolean.TRUE.equals(existe);
    }

    private static boolean vigenciaVencida(CapturaRfid1Persistida captura, Instant ahora) {
        return "VISTA_PREVIA".equals(captura.estado())
                ? captura.confirmacionVenceEn() == null || !captura.confirmacionVenceEn().isAfter(ahora)
                : !captura.venceEn().isAfter(ahora);
    }

    private static boolean estaActiva(CapturaRfid1Persistida captura) {
        return captura != null && ("PENDIENTE".equals(captura.estado())
                || "ESCANEANDO".equals(captura.estado()) || "VISTA_PREVIA".equals(captura.estado()));
    }

    private static ResultadoLecturaRfid1 resultadoNoVigente() {
        return new ResultadoLecturaRfid1(null, null, CAPTURA_NO_VIGENTE, false);
    }

    private static void exigirUnaFila(int filas) {
        if (filas != 1) {
            throw new DataAccessResourceFailureException("No se pudo aplicar la transición de captura RFID.");
        }
    }
}
