package mx.smartparking.api.vision;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.PublicadorVisionAdministracion;
import mx.smartparking.api.vision.ContratosVision.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

/**
 * Guarda la configuración de la cámara y sus observaciones completas para mantener actualizada la
 * ocupación.
 */
@Service
public class ServicioVision {
    private static final int MAXIMO_ZONAS_SOLICITUD = 1000;
    private static final int LIMITE_PURGA_POR_SOLICITUD = 4;
    private static final int LIMITE_PURGA_PROGRAMADA = 1000;
    private final JdbcTemplate jdbc;
    private final Clock reloj;
    private final long frescuraSegundos;
    private final long antiguedadMaximaSegundos;
    private final long futuroMaximoSegundos;
    private final long retencionRecibosSegundos;
    private final int maximoRecibosPorFuente;
    private final Runnable solicitarInvalidacion;

    @Autowired
    public ServicioVision(JdbcTemplate jdbc, PublicadorVisionAdministracion publicador,
            @Value("${smartparking.vision.frescura-segundos:45}") long frescuraSegundos,
            @Value("${smartparking.vision.antiguedad-maxima-segundos:15}") long antiguedadMaximaSegundos,
            @Value("${smartparking.vision.futuro-maximo-segundos:3}") long futuroMaximoSegundos,
            @Value("${smartparking.vision.retencion-recibos-segundos:300}") long retencionRecibosSegundos,
            @Value("${smartparking.vision.max-recibos-por-fuente:4096}") int maximoRecibosPorFuente) {
        this(jdbc, Clock.systemUTC(), frescuraSegundos, antiguedadMaximaSegundos, futuroMaximoSegundos,
                retencionRecibosSegundos, maximoRecibosPorFuente, publicador::solicitar);
    }

    ServicioVision(JdbcTemplate jdbc, Clock reloj, long frescuraSegundos,
            long antiguedadMaximaSegundos, long futuroMaximoSegundos) {
        this(jdbc, reloj, frescuraSegundos, antiguedadMaximaSegundos, futuroMaximoSegundos, 300, 4096);
    }

    ServicioVision(JdbcTemplate jdbc, Clock reloj, long frescuraSegundos,
            long antiguedadMaximaSegundos, long futuroMaximoSegundos, long retencionRecibosSegundos) {
        this(jdbc, reloj, frescuraSegundos, antiguedadMaximaSegundos, futuroMaximoSegundos,
                retencionRecibosSegundos, 4096);
    }

    ServicioVision(JdbcTemplate jdbc, Clock reloj, long frescuraSegundos,
            long antiguedadMaximaSegundos, long futuroMaximoSegundos, long retencionRecibosSegundos,
            int maximoRecibosPorFuente) {
        this(jdbc, reloj, frescuraSegundos, antiguedadMaximaSegundos, futuroMaximoSegundos,
                retencionRecibosSegundos, maximoRecibosPorFuente, () -> { });
    }

    ServicioVision(JdbcTemplate jdbc, Clock reloj, long frescuraSegundos,
            long antiguedadMaximaSegundos, long futuroMaximoSegundos, long retencionRecibosSegundos,
            int maximoRecibosPorFuente, Runnable solicitarInvalidacion) {
        if (frescuraSegundos < 1 || antiguedadMaximaSegundos < 1
                || antiguedadMaximaSegundos > frescuraSegundos || futuroMaximoSegundos < 0
                || frescuraSegundos > 86400 || futuroMaximoSegundos > 60
                || retencionRecibosSegundos <= antiguedadMaximaSegundos + futuroMaximoSegundos
                || retencionRecibosSegundos > 2_592_000
                || maximoRecibosPorFuente < 2 || maximoRecibosPorFuente > 100_000) {
            throw new IllegalArgumentException("La configuración de frescura o retención Vision no es válida.");
        }
        this.jdbc = jdbc;
        this.reloj = reloj;
        this.frescuraSegundos = frescuraSegundos;
        this.antiguedadMaximaSegundos = antiguedadMaximaSegundos;
        this.futuroMaximoSegundos = futuroMaximoSegundos;
        this.retencionRecibosSegundos = retencionRecibosSegundos;
        this.maximoRecibosPorFuente = maximoRecibosPorFuente;
        this.solicitarInvalidacion = Objects.requireNonNull(solicitarInvalidacion);
    }

    /** Registra una cámara para el estacionamiento que ya está configurado. */
    @Transactional
    public RespuestaFuente registrarFuente(SolicitudFuente solicitud) {
        if (solicitud == null || solicitud.fuenteId() == null) {
            throw solicitudInvalida();
        }
        UUID estacionamientoId = estacionamientoActual();
        try {
            jdbc.update("INSERT INTO vision_fuente (fuente_id, estacionamiento_id) VALUES (?, ?)",
                    solicitud.fuenteId(), estacionamientoId);
        } catch (DataIntegrityViolationException excepcion) {
            throw conflicto("La fuente ya existe.");
        }
        return new RespuestaFuente(solicitud.fuenteId());
    }

    /** Consulta en un mismo momento la distribución activa de los lugares que observa la cámara. */
    @Transactional(readOnly = true)
    public RespuestaCalibracion consultarCalibracion(UUID fuenteId) {
        if (fuenteId == null) {
            throw solicitudInvalida();
        }
        List<FilaCalibracion> filas = jdbc.query("""
                SELECT z.vision_zone_id, c.etiqueta, z.cajon_id
                FROM vision_fuente f
                JOIN configuracion_estacionamiento e ON e.estacionamiento_id = f.estacionamiento_id
                    AND e.id = 1 AND e.estado = 'CONFIGURADA'
                LEFT JOIN vision_zona z ON z.fuente_id = f.fuente_id AND z.activa = TRUE
                LEFT JOIN vision_cajon c ON c.cajon_id = z.cajon_id
                WHERE f.fuente_id = ?
                ORDER BY z.vision_zone_id
                """, (rs, numero) -> new FilaCalibracion(rs.getObject("vision_zone_id", UUID.class),
                    rs.getString("etiqueta"), rs.getObject("cajon_id", UUID.class)), fuenteId);
        if (filas.isEmpty() || filas.get(0).zonaId() == null) {
            throw conflicto("La fuente no tiene una calibración activa en el estacionamiento actual.");
        }
        List<ZonaConfiguracion> zonas = filas.stream().filter(fila -> fila.zonaId() != null)
                .map(fila -> new ZonaConfiguracion(fila.zonaId(), fila.etiqueta(), fila.cajonId())).toList();
        return new RespuestaCalibracion(fuenteId, zonas);
    }

    private record FilaCalibracion(UUID zonaId, String etiqueta, UUID cajonId) { }

    /** Activa la distribución elegida para la cámara y cierra el acceso anterior de esa fuente. */
    @Transactional
    public RespuestaCalibracion activarCalibracion(UUID fuenteId, SolicitudCalibracion solicitud) {
        validarCalibracion(solicitud);
        UUID estacionamientoId = estacionamientoActual();
        Fuente fuente = bloquearFuente(fuenteId);
        if (!fuente.estacionamientoId().equals(estacionamientoId)) {
            throw conflicto("La fuente no pertenece al estacionamiento actual.");
        }
        Map<UUID, ZonaExistente> anteriores = new HashMap<>();
        jdbc.query("""
                SELECT z.vision_zone_id, z.cajon_id, z.activa, c.etiqueta
                FROM vision_zona z JOIN vision_cajon c ON c.cajon_id = z.cajon_id WHERE z.fuente_id = ?
                """, rs -> {
            anteriores.put(rs.getObject(1, UUID.class),
                    new ZonaExistente(rs.getObject(2, UUID.class), rs.getBoolean(3), rs.getString(4)));
        }, fuenteId);
        List<ZonaConfiguracion> mapeo = new ArrayList<>();
        Set<UUID> cajones = new HashSet<>();
        for (ZonaConfiguracion zona : solicitud.zonas()) {
            ZonaExistente anterior = anteriores.get(zona.visionZoneId());
            UUID cajonId;
            if (anterior != null) {
                if ((zona.cajonId() != null && !zona.cajonId().equals(anterior.cajonId()))
                        || (!anterior.activa() && !anterior.cajonId().equals(zona.cajonId()))) {
                    throw conflicto("La zona existente requiere conservar su cajón explícitamente.");
                }
                cajonId = anterior.cajonId();
            } else if (zona.cajonId() != null) {
                cajonId = zona.cajonId();
                Integer cantidad = jdbc.queryForObject(
                        "SELECT count(*) FROM vision_cajon WHERE cajon_id = ? AND estacionamiento_id = ?",
                        Integer.class, cajonId, estacionamientoId);
                if (cantidad == null || cantidad != 1) {
                    throw conflicto("El cajón indicado no existe en este estacionamiento.");
                }
            } else {
                cajonId = UUID.randomUUID();
                jdbc.update("INSERT INTO vision_cajon (cajon_id, estacionamiento_id, etiqueta) VALUES (?, ?, ?)",
                        cajonId, estacionamientoId, zona.etiqueta().strip());
            }
            if (!cajones.add(cajonId)) {
                throw conflicto("Un cajón no puede estar asignado a dos zonas activas.");
            }
            mapeo.add(new ZonaConfiguracion(zona.visionZoneId(), zona.etiqueta().strip(), cajonId));
        }

        jdbc.update("UPDATE vision_zona SET activa = FALSE WHERE fuente_id = ?", fuenteId);
        try {
            for (ZonaConfiguracion zona : mapeo) {
                jdbc.update("UPDATE vision_cajon SET etiqueta = ? WHERE cajon_id = ?",
                        zona.etiqueta(), zona.cajonId());
                jdbc.update("""
                        INSERT INTO vision_zona (fuente_id, vision_zone_id, cajon_id, activa)
                        VALUES (?, ?, ?, TRUE)
                        ON CONFLICT (fuente_id, vision_zone_id) DO UPDATE SET activa = TRUE
                        """, fuenteId, zona.visionZoneId(), zona.cajonId());
            }
        } catch (DataIntegrityViolationException excepcion) {
            throw conflicto("Un cajón ya está asignado a otra zona activa.");
        }
        jdbc.update("""
                UPDATE vision_fuente SET sesion_id = NULL, ultima_secuencia = 0,
                    calibracion_activada_en = ? WHERE fuente_id = ?
                """, Timestamp.from(reloj.instant().truncatedTo(ChronoUnit.MICROS)), fuenteId);
        invalidarTrasCommit();
        return new RespuestaCalibracion(fuenteId, List.copyOf(mapeo));
    }

    /**
     * Prepara una nueva comunicación con la cámara y no vuelve a activar una anterior si se repite su
     * identificador.
     */
    @Transactional
    public RespuestaSesion abrirSesion(SolicitudSesion solicitud) {
        if (solicitud == null || solicitud.fuenteId() == null || solicitud.solicitudId() == null
                || solicitud.iniciadaEn() == null) {
            throw solicitudInvalida();
        }
        UUID estacionamientoId = estacionamientoActual();
        Fuente fuente = bloquearFuente(solicitud.fuenteId());
        if (!fuente.estacionamientoId().equals(estacionamientoId)) {
            throw conflicto("La fuente no pertenece al estacionamiento actual.");
        }
        Boolean tieneZonasActivas = jdbc.queryForObject(
                "SELECT EXISTS (SELECT 1 FROM vision_zona WHERE fuente_id = ? AND activa)",
                Boolean.class, solicitud.fuenteId());
        if (!Boolean.TRUE.equals(tieneZonasActivas)) {
            throw conflicto("La fuente no tiene una calibración activa.");
        }
        Instant iniciada = solicitud.iniciadaEn().truncatedTo(ChronoUnit.MICROS);
        String huella = hash("SESION|" + solicitud.fuenteId() + "|" + solicitud.solicitudId()
                + "|" + solicitud.iniciadaEn());
        Recibo previo = buscarRecibo(solicitud.fuenteId(), solicitud.solicitudId());
        if (previo != null) {
            verificarRecibo(previo, "SESION", huella);
            if (!previo.sesionId().equals(fuente.sesionId())) {
                throw conflicto("La sesión fue reemplazada.");
            }
            borrarRecibosVencidos(solicitud.fuenteId(), LIMITE_PURGA_POR_SOLICITUD);
            return new RespuestaSesion(previo.sesionId());
        }
        Instant ahora = reloj.instant();
        if (iniciada.isAfter(ahora.plusSeconds(futuroMaximoSegundos))
                || (fuente.sesionIniciada() != null && !iniciada.isAfter(fuente.sesionIniciada()))
                || fuente.calibracionActivada() == null || !iniciada.isAfter(fuente.calibracionActivada())) {
            throw conflicto("La apertura no corresponde a un inicio actual posterior a la calibración y sesión previas.");
        }
        UUID sesionId = UUID.randomUUID();
        jdbc.update("UPDATE vision_fuente SET sesion_id = ?, sesion_iniciada_en = ?, ultima_secuencia = 0 "
                + "WHERE fuente_id = ?", sesionId, Timestamp.from(iniciada), solicitud.fuenteId());
        guardarRecibo(solicitud.fuenteId(), solicitud.solicitudId(), "SESION", huella, sesionId);
        invalidarTrasCommit();
        return new RespuestaSesion(sesionId);
    }

    /** Acepta una observación solo cuando incluye todos los lugares de la distribución activa. */
    @Transactional
    public RespuestaObservacion observar(SolicitudObservacion solicitud) {
        validarObservacion(solicitud);
        UUID estacionamientoId = estacionamientoActual();
        Fuente fuente = bloquearFuente(solicitud.fuenteId());
        if (!fuente.estacionamientoId().equals(estacionamientoId)) {
            throw conflicto("La fuente no pertenece al estacionamiento actual.");
        }
        Recibo previo = buscarRecibo(solicitud.fuenteId(), solicitud.solicitudId());
        if (previo != null) {
            verificarRecibo(previo, "OBSERVACION", null);
            if (!previo.sesionId().equals(fuente.sesionId())) {
                throw conflicto("La sesión fue reemplazada.");
            }
            borrarRecibosVencidos(solicitud.fuenteId(), LIMITE_PURGA_POR_SOLICITUD);
            return new RespuestaObservacion(true);
        }
        if (fuente.sesionId() == null || !fuente.sesionId().equals(solicitud.sesionId())) {
            throw conflicto("La sesión no está activa.");
        }
        Instant observado = solicitud.observadoEn().truncatedTo(ChronoUnit.MICROS);
        Instant ahora = reloj.instant();
        if (observado.isBefore(ahora.minusSeconds(antiguedadMaximaSegundos))
                || observado.isAfter(ahora.plusSeconds(futuroMaximoSegundos))) {
            throw conflicto("La observación está fuera del intervalo permitido.");
        }
        if (solicitud.secuencia() <= fuente.ultimaSecuencia()
                || (fuente.ultimoObservado() != null && !observado.isAfter(fuente.ultimoObservado()))) {
            throw conflicto("La observación no es posterior a la última aceptada.");
        }
        Map<UUID, ZonaActiva> zonasActivas = new HashMap<>();
        jdbc.query("""
                SELECT z.vision_zone_id, z.cajon_id, o.ultimo_estado, o.observado_en,
                       o.fuente_id AS fuente_observada, o.sesion_id AS sesion_observada
                FROM vision_zona z LEFT JOIN vision_ocupacion o ON o.cajon_id = z.cajon_id
                WHERE z.fuente_id = ? AND z.activa
                """, rs -> {
            Timestamp marca = rs.getTimestamp("observado_en");
            Instant anterior = marca == null ? null : marca.toInstant();
            String ultimo = rs.getString("ultimo_estado");
            boolean vigente = vigente(ultimo, anterior, ahora, solicitud.fuenteId(), fuente.sesionId(),
                    rs.getObject("fuente_observada", UUID.class), rs.getObject("sesion_observada", UUID.class));
            zonasActivas.put(rs.getObject("vision_zone_id", UUID.class),
                    new ZonaActiva(rs.getObject("cajon_id", UUID.class), vigente ? ultimo : "NO_VERIFICABLE"));
        }, solicitud.fuenteId());
        Set<UUID> recibidas = new HashSet<>();
        for (ZonaObservacion zona : solicitud.zonas()) {
            recibidas.add(zona.visionZoneId());
        }
        if (!zonasActivas.keySet().equals(recibidas)) {
            throw conflicto("El snapshot debe contener exactamente las zonas activas.");
        }
        boolean cambioEfectivo = false;
        for (ZonaObservacion zona : solicitud.zonas()) {
            ZonaActiva anterior = zonasActivas.get(zona.visionZoneId());
            cambioEfectivo |= !zona.estado().equals(anterior.estadoEfectivo());
            jdbc.update("""
                    INSERT INTO vision_ocupacion (cajon_id, fuente_id, sesion_id, revision_calibracion,
                        hash_calibracion, ultimo_estado, observado_en, recibido_en)
                    VALUES (?, ?, ?, NULL, NULL, ?, ?, ?)
                    ON CONFLICT (cajon_id) DO UPDATE SET fuente_id = EXCLUDED.fuente_id,
                        sesion_id = EXCLUDED.sesion_id, revision_calibracion = NULL,
                        hash_calibracion = NULL, ultimo_estado = EXCLUDED.ultimo_estado,
                        observado_en = EXCLUDED.observado_en, recibido_en = EXCLUDED.recibido_en
                    """, anterior.cajonId(), solicitud.fuenteId(), solicitud.sesionId(),
                    zona.estado(), Timestamp.from(observado), Timestamp.from(ahora));
        }
        jdbc.update("UPDATE vision_fuente SET ultima_secuencia = ?, ultimo_observado_en = ? WHERE fuente_id = ?",
                solicitud.secuencia(), Timestamp.from(observado), solicitud.fuenteId());
        guardarRecibo(solicitud.fuenteId(), solicitud.solicitudId(), "OBSERVACION", null, solicitud.sesionId());
        if (cambioEfectivo) invalidarTrasCommit();
        return new RespuestaObservacion(true);
    }

    /** Muestra los lugares y su estado de ocupación según la última información válida de la cámara. */
    @Transactional(readOnly = true)
    public List<EstadoCajon> consultarCajones() {
        return leerCajonesConVigencia().cajones();
    }

    /** Muestra los lugares y el tiempo que falta para que venza el primer dato de ocupación. */
    @Transactional(readOnly = true)
    public LecturaCajones consultarCajonesConVigencia() {
        return leerCajonesConVigencia();
    }

    /** Cambia solamente el nombre visible de un lugar asociado a la cámara. */
    @Transactional
    public void actualizarNombreCajon(UUID cajonId, String displayName) {
        if (cajonId == null) {
            throw solicitudInvalida();
        }
        UUID estacionamientoId = estacionamientoActual();
        // La activación de la calibración espera su turno sobre esta misma cámara.
        List<UUID> fuentes = jdbc.query("""
                SELECT f.fuente_id FROM vision_cajon c
                JOIN vision_zona z ON z.cajon_id = c.cajon_id AND z.activa
                JOIN vision_fuente f ON f.fuente_id = z.fuente_id
                WHERE c.cajon_id = ? AND c.estacionamiento_id = ?
                FOR UPDATE OF f
                """, (rs, numero) -> rs.getObject(1, UUID.class), cajonId, estacionamientoId);
        if (fuentes.size() != 1) {
            throw conflicto("El cajón no está activo en el estacionamiento actual.");
        }
        String nombre = displayName == null || displayName.isBlank() ? null : displayName;
        int actualizados = jdbc.update("""
                UPDATE vision_cajon c SET display_name = ?
                WHERE c.cajon_id = ? AND c.estacionamiento_id = ?
                  AND EXISTS (SELECT 1 FROM vision_zona z
                      JOIN vision_fuente f ON f.fuente_id = z.fuente_id
                      WHERE z.cajon_id = c.cajon_id AND z.activa AND f.fuente_id = ?)
                """, nombre, cajonId, estacionamientoId, fuentes.get(0));
        if (actualizados != 1) {
            throw conflicto("El cajón no está activo en el estacionamiento actual.");
        }
        invalidarTrasCommit();
    }

    private LecturaCajones leerCajonesConVigencia() {
        UUID estacionamientoId = estacionamientoActualSinBloqueo();
        Instant ahora = reloj.instant();
        List<EstadoCajon> cajones = jdbc.query("""
                SELECT c.cajon_id, c.etiqueta, c.display_name, o.ultimo_estado, o.observado_en,
                       o.fuente_id AS fuente_observada, o.sesion_id AS sesion_observada,
                       f.fuente_id AS fuente_activa, f.sesion_id AS sesion_activa
                FROM vision_cajon c
                JOIN vision_zona z ON z.cajon_id = c.cajon_id AND z.activa
                JOIN vision_fuente f ON f.fuente_id = z.fuente_id
                LEFT JOIN vision_ocupacion o ON o.cajon_id = c.cajon_id
                WHERE c.estacionamiento_id = ? ORDER BY c.etiqueta, c.cajon_id
                """, (rs, numero) -> {
            Timestamp marca = rs.getTimestamp("observado_en");
            Instant observado = marca == null ? null : marca.toInstant();
            UUID fuenteActiva = rs.getObject("fuente_activa", UUID.class);
            UUID sesionActiva = rs.getObject("sesion_activa", UUID.class);
            String ultimo = rs.getString("ultimo_estado");
            boolean vigente = vigente(ultimo, observado, ahora, fuenteActiva, sesionActiva,
                    rs.getObject("fuente_observada", UUID.class), rs.getObject("sesion_observada", UUID.class));
            return new EstadoCajon(rs.getObject("cajon_id", UUID.class), rs.getString("etiqueta"),
                    vigente ? ultimo : "NO_VERIFICABLE", ultimo, observado, rs.getString("display_name"));
        }, estacionamientoId);
        Long restante = cajones.stream().filter(cajon -> !"NO_VERIFICABLE".equals(cajon.estado()))
                .map(cajon -> Math.max(0L, java.time.Duration.between(ahora,
                        cajon.observadoEn().plusSeconds(frescuraSegundos)).toMillis()))
                .min(Long::compareTo).orElse(null);
        return new LecturaCajones(List.copyOf(cajones), restante);
    }

    private boolean vigente(String ultimo, Instant observado, Instant ahora, UUID fuenteActiva, UUID sesionActiva,
            UUID fuenteObservada, UUID sesionObservada) {
        return observado != null && ultimo != null && fuenteActiva != null && sesionActiva != null
                && fuenteActiva.equals(fuenteObservada) && sesionActiva.equals(sesionObservada)
                && !observado.isBefore(ahora.minusSeconds(frescuraSegundos))
                && !observado.isAfter(ahora.plusSeconds(futuroMaximoSegundos));
    }

    private void invalidarTrasCommit() {
        if (!TransactionSynchronizationManager.isActualTransactionActive()
                || !TransactionSynchronizationManager.isSynchronizationActive()) {
            throw new IllegalStateException("La invalidación Vision requiere una transacción activa.");
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                try {
                    solicitarInvalidacion.run();
                } catch (RuntimeException excepcion) {
                    // El cambio ya se guardó; la pantalla podrá recuperar la información al consultar de nuevo.
                }
            }
        });
    }

    /** Reúne los lugares consultados y el tiempo que queda antes de que cambie la vigencia de sus datos. */
    public record LecturaCajones(List<EstadoCajon> cajones, Long vigenciaRestanteMs) { }

    private record ZonaActiva(UUID cajonId, String estadoEfectivo) { }

    private UUID estacionamientoActual() {
        return obtenerEstacionamiento(" FOR SHARE");
    }

    private UUID estacionamientoActualSinBloqueo() {
        return obtenerEstacionamiento("");
    }

    private UUID obtenerEstacionamiento(String bloqueo) {
        List<UUID> ids = jdbc.query("SELECT estacionamiento_id FROM configuracion_estacionamiento "
                + "WHERE id = 1 AND estado = 'CONFIGURADA'" + bloqueo,
                (rs, numero) -> rs.getObject(1, UUID.class));
        if (ids.size() != 1 || ids.get(0) == null) {
            throw conflicto("El estacionamiento no está configurado.");
        }
        return ids.get(0);
    }

    private Fuente bloquearFuente(UUID fuenteId) {
        if (fuenteId == null) {
            throw solicitudInvalida();
        }
        List<Fuente> fuentes = jdbc.query("""
                SELECT estacionamiento_id, sesion_id, sesion_iniciada_en, calibracion_activada_en,
                       ultima_secuencia, ultimo_observado_en
                FROM vision_fuente WHERE fuente_id = ? FOR UPDATE
                """, (rs, numero) -> {
            Timestamp fecha = rs.getTimestamp("ultimo_observado_en");
            Timestamp inicio = rs.getTimestamp("sesion_iniciada_en");
            Timestamp activacion = rs.getTimestamp("calibracion_activada_en");
            return new Fuente(rs.getObject("estacionamiento_id", UUID.class),
                    rs.getObject("sesion_id", UUID.class), rs.getLong("ultima_secuencia"),
                    fecha == null ? null : fecha.toInstant(),
                    inicio == null ? null : inicio.toInstant(), activacion == null ? null : activacion.toInstant());
        }, fuenteId);
        if (fuentes.isEmpty()) {
            throw conflicto("La fuente no está registrada.");
        }
        return fuentes.get(0);
    }

    private Recibo buscarRecibo(UUID fuenteId, UUID solicitudId) {
        List<Recibo> recibos = jdbc.query("""
                SELECT tipo, hash_contenido, sesion_id FROM vision_solicitud WHERE fuente_id = ? AND solicitud_id = ?
                """, (rs, numero) -> new Recibo(rs.getString(1), rs.getString(2), rs.getObject(3, UUID.class)),
                fuenteId, solicitudId);
        return recibos.isEmpty() ? null : recibos.get(0);
    }

    private void guardarRecibo(UUID fuenteId, UUID solicitudId, String tipo, String huella, UUID sesionId) {
        // Mientras se guardan estos datos, otra operación no puede cambiar esta fuente al mismo tiempo.
        borrarRecibosVencidos(fuenteId, LIMITE_PURGA_POR_SOLICITUD);
        Long cantidad = jdbc.queryForObject(
                "SELECT count(*) FROM vision_solicitud WHERE fuente_id = ?", Long.class, fuenteId);
        if (cantidad == null || cantidad >= maximoRecibosPorFuente) {
            throw new ErrorConfiguracion(HttpStatus.TOO_MANY_REQUESTS,
                    "La fuente alcanzó temporalmente el límite de recibos Vision.", "VISION_RETENCION_LLENA");
        }
        jdbc.update("""
                INSERT INTO vision_solicitud (fuente_id, solicitud_id, tipo, hash_contenido, sesion_id, creado_en)
                VALUES (?, ?, ?, ?, ?, ?)
                """, fuenteId, solicitudId, tipo, huella, sesionId, Timestamp.from(reloj.instant()));
    }

    /** Elimina un grupo de registros antiguos si la cámara no está ocupada guardando una observación. */
    @Transactional
    public int limpiarRecibos(UUID fuenteId) {
        List<UUID> bloqueadas = jdbc.query("""
                SELECT fuente_id FROM vision_fuente WHERE fuente_id = ? FOR UPDATE SKIP LOCKED
                """, (rs, numero) -> rs.getObject(1, UUID.class), fuenteId);
        return bloqueadas.isEmpty() ? 0 : borrarRecibosVencidos(fuenteId, LIMITE_PURGA_PROGRAMADA);
    }

    private int borrarRecibosVencidos(UUID fuenteId, int limite) {
        Instant limiteRetencion = reloj.instant().minusSeconds(retencionRecibosSegundos);
        return jdbc.update("""
                DELETE FROM vision_solicitud recibo
                WHERE recibo.fuente_id = ? AND recibo.solicitud_id IN (
                    SELECT anterior.solicitud_id
                    FROM vision_solicitud anterior
                    JOIN vision_fuente fuente ON fuente.fuente_id = anterior.fuente_id
                    WHERE anterior.fuente_id = ? AND anterior.creado_en < ?
                      AND (anterior.tipo <> 'SESION' OR anterior.sesion_id IS DISTINCT FROM fuente.sesion_id)
                    ORDER BY anterior.creado_en, anterior.solicitud_id
                    LIMIT ?
                )
                """, fuenteId, fuenteId, Timestamp.from(limiteRetencion), limite);
    }

    private static void verificarRecibo(Recibo recibo, String tipo, String huella) {
        if (!tipo.equals(recibo.tipo()) || (huella != null && !huella.equals(recibo.huella()))) {
            throw conflicto("El identificador de solicitud ya se utilizó con otro contenido.");
        }
    }

    private static void validarCalibracion(SolicitudCalibracion solicitud) {
        if (solicitud == null || solicitud.zonas() == null || solicitud.zonas().isEmpty()
                || solicitud.zonas().size() > MAXIMO_ZONAS_SOLICITUD) {
            throw solicitudInvalida();
        }
        Set<UUID> ids = new HashSet<>();
        for (ZonaConfiguracion zona : solicitud.zonas()) {
            if (zona == null || zona.visionZoneId() == null || !ids.add(zona.visionZoneId())
                    || zona.etiqueta() == null || zona.etiqueta().isBlank() || zona.etiqueta().length() > 100
                    || zona.etiqueta().chars().anyMatch(Character::isISOControl)) {
                throw solicitudInvalida();
            }
        }
    }

    private static void validarObservacion(SolicitudObservacion solicitud) {
        if (solicitud == null || solicitud.fuenteId() == null || solicitud.sesionId() == null
                || solicitud.solicitudId() == null || solicitud.secuencia() == null || solicitud.secuencia() < 1
                || solicitud.observadoEn() == null || solicitud.zonas() == null || solicitud.zonas().isEmpty()
                || solicitud.zonas().size() > MAXIMO_ZONAS_SOLICITUD) {
            throw solicitudInvalida();
        }
        Set<UUID> ids = new HashSet<>();
        for (ZonaObservacion zona : solicitud.zonas()) {
            if (zona == null || zona.visionZoneId() == null || !ids.add(zona.visionZoneId())
                    || !("LIBRE".equals(zona.estado()) || "OCUPADO".equals(zona.estado()))) {
                throw solicitudInvalida();
            }
        }
    }

    private static String hash(String contenido) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(contenido.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException("SHA-256 no está disponible.", excepcion);
        }
    }

    private static ErrorConfiguracion solicitudInvalida() {
        return new ErrorConfiguracion(HttpStatus.BAD_REQUEST, "La solicitud de Vision no es válida.", "VISION_INVALIDA");
    }

    private static ErrorConfiguracion conflicto(String mensaje) {
        return new ErrorConfiguracion(HttpStatus.CONFLICT, mensaje, "VISION_CONFLICTO");
    }

    private record Fuente(UUID estacionamientoId, UUID sesionId, long ultimaSecuencia, Instant ultimoObservado,
            Instant sesionIniciada, Instant calibracionActivada) { }
    private record ZonaExistente(UUID cajonId, boolean activa, String etiqueta) { }
    private record Recibo(String tipo, String huella, UUID sesionId) { }
}
