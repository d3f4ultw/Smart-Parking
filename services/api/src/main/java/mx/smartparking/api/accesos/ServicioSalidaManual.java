package mx.smartparking.api.accesos;

import jakarta.servlet.http.HttpSession;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.PublicadorAccesoAdministracion;
import mx.smartparking.api.historial.persistencia.RepositorioEventoAccesoJdbc;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.HuellaSesionPropietario;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Administra la solicitud de una salida manual ligada a una visita y a la persona que la solicitó. */
@Service
public class ServicioSalidaManual {
    private static final int ESPACIO_BLOQUEO_MANUAL = 0x534D414E;
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaccion;
    private final GestorSesionesPropietario sesiones;
    private final RepositorioCuentas cuentas;
    private final RepositorioEventoAccesoJdbc eventos;
    private final PublicadorAccesoAdministracion publicador;
    private final AutenticadorSalidaManual autenticador;
    private final DetectorCapacidadSalidaManual detector;

    public ServicioSalidaManual(JdbcTemplate jdbc, PlatformTransactionManager administrador,
            GestorSesionesPropietario sesiones, RepositorioCuentas cuentas,
            RepositorioEventoAccesoJdbc eventos, PublicadorAccesoAdministracion publicador,
            AutenticadorSalidaManual autenticador, DetectorCapacidadSalidaManual detector) {
        this.jdbc = jdbc;
        this.transaccion = new TransactionTemplate(administrador);
        this.transaccion.setTimeout(3);
        this.sesiones = sesiones;
        this.cuentas = cuentas;
        this.eventos = eventos;
        this.publicador = publicador;
        this.autenticador = autenticador;
        this.detector = detector;
    }

    /** Registra la solicitud de salida manual sin cerrar todavía la visita ni abrir la barrera. */
    public Respuesta solicitar(String movimientoTexto, String clave, PrincipalPropietario principal, HttpSession sesion) {
        exigirActor(principal, sesion);
        long movimientoId = movimientoId(movimientoTexto);
        UUID operacion = uuid(clave);
        String huella = HuellaSesionPropietario.calcular(sesion.getId());
        synchronized (detector) {
          return transaccion.execute(status -> {
            jdbc.query("SELECT pg_advisory_xact_lock(?, ?)", rs -> null,
                    ESPACIO_BLOQUEO_MANUAL, claveBloqueo(operacion));
            Solicitud previa = buscar(operacion, false);
            if (previa != null) {
                if (previa.movimientoId() != movimientoId || !previa.cuentaId().equals(principal.cuentaId())) {
                    throw conflicto();
                }
                return respuesta(previa);
            }
            Movimiento movimiento = bloquearMovimiento(movimientoId);
            if (!movimiento.abierto() || !"CANCELADA".equals(movimiento.estadoTarjeta())) {
                throw conflicto();
            }
            expirarSolicitudes(movimientoId);
            Integer activas = jdbc.queryForObject("""
                    SELECT count(*) FROM solicitud_salida_manual WHERE movimiento_id = ?
                    AND estado IN ('PENDIENTE', 'EMITIDA', 'INCIERTA')
                    """, Integer.class, movimientoId);
            if (activas == null || activas != 0) {
                throw conflicto();
            }
            exigirAutenticador();
            if (!detector.disponibilidad().disponible()) {
                throw noDisponible();
            }
            jdbc.update("""
                    INSERT INTO solicitud_salida_manual
                    (operacion_id, movimiento_id, solicitante_cuenta_id, solicitante_rol,
                     revision_acceso, revision_propietario, huella_sesion, estado, vence_en)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDIENTE', clock_timestamp() + interval '2 minutes')
                    """, operacion, movimientoId, principal.cuentaId(), principal.rol().name(),
                    principal.revisionAcceso(), principal.revisionPropietario(), huella);
            publicarDespuesDeCommit();
            return new Respuesta(operacion.toString(), Long.toString(movimientoId), "PENDIENTE");
          });
        }
    }

    /** Consulta el resultado actual de una salida manual sin cambiar sus datos. */
    public Respuesta consultar(String operacionTexto) {
        Solicitud solicitud = buscar(uuid(operacionTexto), false);
        if (solicitud == null) {
            throw noEncontrada();
        }
        return respuesta(solicitud);
    }

    /** Busca una salida que el dispositivo pueda preparar o una que ya fue enviada y solo espera respuesta. */
    public TrabajoDispositivo pendiente(String despuesTexto) {
        UUID despues = despuesTexto == null ? null : uuid(despuesTexto);
        List<TrabajoDispositivo> filas = jdbc.query("""
                WITH candidatas AS (
                    SELECT operacion_id, CASE WHEN estado = 'EMITIDA'
                               AND emitida_en + interval '10 seconds' <= clock_timestamp()
                               THEN 'INCIERTA' ELSE estado END AS estado, boot_id, ticket_id, creada_en,
                           CASE WHEN estado = 'PENDIENTE' THEN 0 ELSE 1 END AS prioridad
                    FROM solicitud_salida_manual
                    WHERE (estado = 'PENDIENTE' AND vence_en > clock_timestamp())
                       OR estado IN ('EMITIDA', 'INCIERTA')
                ), referencia AS (
                    SELECT prioridad, creada_en, operacion_id FROM candidatas WHERE operacion_id = ?
                )
                SELECT operacion_id, estado, boot_id, ticket_id FROM candidatas
                ORDER BY CASE WHEN NOT EXISTS (SELECT 1 FROM referencia)
                                    OR (prioridad, creada_en, operacion_id) >
                                       (SELECT prioridad, creada_en, operacion_id FROM referencia)
                              THEN 0 ELSE 1 END,
                         prioridad, creada_en, operacion_id
                LIMIT 1
                """, (rs, n) -> new TrabajoDispositivo(rs.getObject(1, UUID.class).toString(),
                rs.getString(2), rs.getString(3), rs.getString(4)), despues);
        return filas.isEmpty() ? null : filas.getFirst();
    }

    /** Entrega el permiso una sola vez, después de que la solicitud quedó guardada. */
    public String emitir(String operacionTexto, String bootId, String ticketId) {
        UUID operacion = uuid(operacionTexto);
        validarIdentificador(bootId);
        validarIdentificador(ticketId);
        exigirAutenticador();
        // Si alguien cierra la sesión al mismo tiempo, se espera a guardar la decisión.
        // Una sesión que ya fue cerrada no puede autorizar la salida.
        synchronized (detector) {
          synchronized (sesiones) {
            return transaccion.execute(status -> {
                Solicitud inicial = buscar(operacion, false);
                if (inicial == null) {
                    return null;
                }
                jdbc.query("SELECT id FROM configuracion_estacionamiento WHERE id = 1 FOR UPDATE", rs -> null);
                jdbc.query("SELECT id FROM cuenta WHERE id = ? FOR UPDATE", rs -> null, inicial.cuentaId());
                Movimiento movimiento = bloquearMovimiento(inicial.movimientoId());
                Solicitud actual = buscar(operacion, true);
                if (actual == null || !"PENDIENTE".equals(actual.estado())) {
                    return null;
                }
                boolean autorizada = actual.vigente() && movimiento.abierto()
                        && "CANCELADA".equals(movimiento.estadoTarjeta())
                        && sesiones.estaRegistradaPorHuella(actual.huella(), actual.cuentaId(),
                                actual.revisionAcceso(), actual.revisionPropietario(), actual.rol())
                        && cuentas.sesionVigente(actual.cuentaId(), actual.revisionAcceso(),
                                actual.rol(), actual.revisionPropietario())
                        && detector.disponibleParaBoot(bootId);
                if (!autorizada) {
                    jdbc.update("UPDATE solicitud_salida_manual SET estado = 'ANULADA' WHERE operacion_id = ?", operacion);
                    publicarDespuesDeCommit();
                    return null;
                }
                String firma = autenticador.firmarEjecucion(operacion, bootId, ticketId);
                int cambios = jdbc.update("""
                        UPDATE solicitud_salida_manual SET estado = 'EMITIDA', emitida_en = clock_timestamp(),
                            boot_id = ?, ticket_id = ? WHERE operacion_id = ? AND estado = 'PENDIENTE'
                        """, bootId, ticketId, operacion);
                if (cambios == 1) {
                    publicarDespuesDeCommit();
                }
                return cambios == 1 ? firma : null;
            });
          }
        }
    }

    /** Si el dispositivo repite la respuesta, conserva el resultado anterior y no registra otra salida. */
    public Respuesta resultado(String operacionTexto, String bootId, String ticketId, String resultado, String firma) {
        UUID operacion = uuid(operacionTexto);
        validarIdentificador(bootId);
        validarIdentificador(ticketId);
        if (!"EJECUTADA".equals(resultado) && !"NO_EJECUTADA".equals(resultado)) {
            throw invalida();
        }
        exigirAutenticador();
        if (!autenticador.verificarResultado(operacion, bootId, ticketId, resultado, firma)) {
            throw conflicto();
        }
        return transaccion.execute(status -> {
            Solicitud inicial = buscar(operacion, false);
            if (inicial == null) {
                throw noEncontrada();
            }
            Movimiento movimiento = bloquearMovimiento(inicial.movimientoId());
            Solicitud actual = buscar(operacion, true);
            if (actual == null || !bootId.equals(actual.bootId()) || !ticketId.equals(actual.ticketId())) {
                throw conflicto();
            }
            if (("CONFIRMADA".equals(actual.estado()) && "EJECUTADA".equals(resultado))
                    || ("NO_EJECUTADA".equals(actual.estado()) && "NO_EJECUTADA".equals(resultado))) {
                return respuesta(actual);
            }
            if (!"EMITIDA".equals(actual.estado()) && !"INCIERTA".equals(actual.estado())) {
                throw conflicto();
            }
            if ("NO_EJECUTADA".equals(resultado)) {
                jdbc.update("""
                        UPDATE solicitud_salida_manual SET estado = 'NO_EJECUTADA', resultado_en = clock_timestamp()
                        WHERE operacion_id = ?
                        """, operacion);
                publicarDespuesDeCommit();
                return new Respuesta(operacion.toString(), Long.toString(actual.movimientoId()), "NO_EJECUTADA");
            }
            if (!movimiento.abierto() || !"CANCELADA".equals(movimiento.estadoTarjeta())) {
                throw conflicto();
            }
            String nombreZona = jdbc.queryForObject("""
                    SELECT zona_horaria FROM configuracion_estacionamiento
                    WHERE id = 1 AND estado = 'CONFIGURADA'
                    """, String.class);
            ZoneId zona = ZoneId.of(nombreZona);
            Instant instante = jdbc.queryForObject("SELECT clock_timestamp()", OffsetDateTime.class).toInstant();
            if (instante.isBefore(movimiento.entrada())) {
                throw conflicto();
            }
            var local = instante.atZone(zona);
            int cambios = jdbc.update("""
                    UPDATE movimiento_estacionamiento SET fecha_salida = ?, hora_salida = ?, instante_salida = ?
                    WHERE movimiento_id = ? AND asociacion_id = ? AND instante_salida IS NULL
                    """, local.toLocalDate(), local.toLocalTime(), OffsetDateTime.ofInstant(instante, ZoneOffset.UTC),
                    actual.movimientoId(), movimiento.asociacionId());
            if (cambios != 1) {
                throw conflicto();
            }
            eventos.registrar(instante, "MANUAL", "AUTORIZADA", null, operacion,
                    movimiento.asociacionId(), actual.movimientoId());
            jdbc.update("""
                    UPDATE solicitud_salida_manual SET estado = 'CONFIRMADA', resultado_en = clock_timestamp()
                    WHERE operacion_id = ?
                    """, operacion);
            return new Respuesta(operacion.toString(), Long.toString(actual.movimientoId()), "CONFIRMADA");
        });
    }

    private Movimiento bloquearMovimiento(long id) {
        List<Long> asociaciones = jdbc.query("SELECT asociacion_id FROM movimiento_estacionamiento WHERE movimiento_id = ?",
                (rs, n) -> rs.getLong(1), id);
        if (asociaciones.size() != 1) {
            throw conflicto();
        }
        long asociacion = asociaciones.getFirst();
        List<String> estados = jdbc.query("SELECT estado FROM asociacion_tarjeta_rfid1 WHERE asociacion_id = ? FOR UPDATE",
                (rs, n) -> rs.getString(1), asociacion);
        List<Movimiento> movimientos = jdbc.query("""
                SELECT instante_entrada, instante_salida IS NULL FROM movimiento_estacionamiento
                WHERE movimiento_id = ? AND asociacion_id = ? FOR UPDATE
                """, (rs, n) -> new Movimiento(asociacion, estados.getFirst(),
                rs.getObject(1, OffsetDateTime.class).toInstant(), rs.getBoolean(2)), id, asociacion);
        if (estados.size() != 1 || movimientos.size() != 1) {
            throw conflicto();
        }
        return movimientos.getFirst();
    }

    private void expirarSolicitudes(long movimientoId) {
        jdbc.update("""
                UPDATE solicitud_salida_manual SET estado = 'ANULADA'
                WHERE movimiento_id = ? AND estado = 'PENDIENTE' AND vence_en <= clock_timestamp()
                """, movimientoId);
        jdbc.update("""
                UPDATE solicitud_salida_manual SET estado = 'INCIERTA'
                WHERE movimiento_id = ? AND estado = 'EMITIDA'
                    AND emitida_en + interval '10 seconds' <= clock_timestamp()
                """, movimientoId);
    }

    private Solicitud buscar(UUID operacion, boolean bloquear) {
        String sql = """
                SELECT operacion_id, movimiento_id, solicitante_cuenta_id, solicitante_rol,
                       revision_acceso, revision_propietario, huella_sesion, estado, boot_id, ticket_id,
                       vence_en > clock_timestamp() AS vigente,
                       CASE WHEN estado = 'PENDIENTE' AND vence_en <= clock_timestamp() THEN 'ANULADA'
                            WHEN estado = 'EMITIDA' AND emitida_en + interval '10 seconds' <= clock_timestamp()
                                THEN 'INCIERTA' ELSE estado END AS estado_efectivo
                FROM solicitud_salida_manual WHERE operacion_id = ?
                """ + (bloquear ? " FOR UPDATE" : "");
        List<Solicitud> filas = jdbc.query(sql, (rs, n) -> new Solicitud(
                rs.getObject(1, UUID.class), rs.getLong(2), rs.getObject(3, UUID.class), rs.getString(4),
                rs.getLong(5), rs.getLong(6), rs.getString(7), rs.getString(8), rs.getString(9),
                rs.getString(10), rs.getBoolean(11), rs.getString(12)), operacion);
        return filas.isEmpty() ? null : filas.getFirst();
    }

    private void publicarDespuesDeCommit() {
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override public void afterCommit() { publicador.publicar(); }
        });
    }

    private static Respuesta respuesta(Solicitud solicitud) {
        return new Respuesta(solicitud.operacion().toString(), Long.toString(solicitud.movimientoId()),
                solicitud.estadoEfectivo());
    }

    private static void exigirActor(PrincipalPropietario principal, HttpSession sesion) {
        if (principal == null || sesion == null
                || (principal.rol() != RolCuenta.DUENO && principal.rol() != RolCuenta.OPERADOR)) {
            throw new ErrorConfiguracion(HttpStatus.FORBIDDEN, "No tienes acceso para esta acción.", "PERMISO_INSUFICIENTE");
        }
    }

    private static UUID uuid(String texto) {
        try {
            if (texto == null || !texto.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")) {
                throw new IllegalArgumentException();
            }
            return UUID.fromString(texto);
        } catch (IllegalArgumentException excepcion) {
            throw invalida();
        }
    }
    private static long movimientoId(String texto) {
        try {
            if (texto == null || !texto.matches("[1-9][0-9]*")) { throw new NumberFormatException(); }
            return Long.parseLong(texto);
        } catch (NumberFormatException excepcion) { throw invalida(); }
    }
    private static void validarIdentificador(String texto) {
        if (!AutenticadorSalidaManual.identificadorCanonico(texto)) { throw invalida(); }
    }
    private void exigirAutenticador() {
        if (!autenticador.estaHabilitado()) {
            throw noDisponible();
        }
    }
    private static ErrorConfiguracion noDisponible() {
        return new ErrorConfiguracion(HttpStatus.SERVICE_UNAVAILABLE,
                "La salida manual no está disponible.", "SALIDA_MANUAL_NO_DISPONIBLE");
    }
    private static int claveBloqueo(UUID uuid) {
        long a = uuid.getMostSignificantBits(); long b = uuid.getLeastSignificantBits();
        return (int) (a >>> 32) ^ (int) a ^ (int) (b >>> 32) ^ (int) b;
    }
    private static ErrorConfiguracion invalida() {
        return new ErrorConfiguracion(HttpStatus.BAD_REQUEST, "La solicitud no es válida.", "SOLICITUD_NO_VALIDA");
    }
    private static ErrorConfiguracion conflicto() {
        return new ErrorConfiguracion(HttpStatus.CONFLICT, "No se pudo confirmar esta salida.", "SALIDA_EN_CONFLICTO");
    }
    private static ErrorConfiguracion noEncontrada() {
        return new ErrorConfiguracion(HttpStatus.NOT_FOUND, "No encontramos la solicitud.", "SALIDA_NO_ENCONTRADA");
    }

    public record Respuesta(String operacionId, String movimientoId, String estado) { }
    @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
    public record TrabajoDispositivo(String operacionId, String estado, String bootId, String ticketId) { }
    private record Movimiento(long asociacionId, String estadoTarjeta, Instant entrada, boolean abierto) { }
    private record Solicitud(UUID operacion, long movimientoId, UUID cuentaId, String rol, long revisionAcceso,
                             long revisionPropietario, String huella, String estado, String bootId, String ticketId,
                             boolean vigente, String estadoEfectivo) { }
}
