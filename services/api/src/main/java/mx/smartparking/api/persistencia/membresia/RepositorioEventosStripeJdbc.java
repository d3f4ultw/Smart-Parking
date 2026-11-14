package mx.smartparking.api.persistencia.membresia;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import mx.smartparking.api.clientes.membresia.modelo.ActualizacionStripe;
import mx.smartparking.api.persistencia.CargadorSql;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/** Guarda y aplica los avisos de Stripe en operaciones breves de la base de datos. */
final class RepositorioEventosStripeJdbc {

    private static final String SQL_CONSULTAR_PROYECCION_VISIBLE =
            CargadorSql.cargar("membresias/consultar_proyeccion_visible.sql");
    private static final String SQL_REGISTRAR_EVENTO_STRIPE =
            CargadorSql.cargar("membresias/registrar_evento_stripe.sql");
    private static final String SQL_BUSCAR_CHECKOUT_PARA_EVENTO =
            CargadorSql.cargar("membresias/buscar_checkout_para_evento.sql");
    private static final String SQL_ACTUALIZAR_CHECKOUT_POR_EVENTO =
            CargadorSql.cargar("membresias/actualizar_checkout_por_evento.sql");
    private static final String SQL_INSERTAR_SUSCRIPCION_STRIPE =
            CargadorSql.cargar("membresias/insertar_suscripcion_stripe.sql");
    private static final String SQL_ACTUALIZAR_SUSCRIPCION_STRIPE =
            CargadorSql.cargar("membresias/actualizar_suscripcion_stripe.sql");
    private static final String SQL_BUSCAR_SUSCRIPCION_STRIPE =
            CargadorSql.cargar("membresias/buscar_suscripcion_stripe.sql");
    private static final String SQL_VALIDAR_CUSTOMER_STRIPE =
            CargadorSql.cargar("membresias/validar_customer_stripe.sql");
    private static final String SQL_FINALIZAR_EVENTO_STRIPE =
            CargadorSql.cargar("membresias/finalizar_evento_stripe.sql");
    private static final String SQL_BUSCAR_EVENTO_STRIPE =
            CargadorSql.cargar("membresias/buscar_evento_stripe.sql");
    private static final String SQL_BUSCAR_EVENTO_PARA_ACTUALIZAR =
            CargadorSql.cargar("membresias/buscar_evento_stripe_para_actualizar.sql");
    private static final String SQL_BLOQUEAR_CLIENTE_EVENTO_STRIPE =
            CargadorSql.cargar("membresias/bloquear_cliente_registrado.sql");

    private static final String PRICE_ID = "price_1USQ5HAqtHmR2qmyAWwUp5vy";
    private static final Set<String> EVENTOS_PERMITIDOS = Set.of(
            "customer.subscription.created", "checkout.session.completed", "checkout.session.expired",
            "invoice.paid", "invoice.payment_failed", "customer.subscription.updated",
            "customer.subscription.deleted");
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaccion;

    RepositorioEventosStripeJdbc(JdbcTemplate jdbc, PlatformTransactionManager administradorTransacciones) {
        this.jdbc = jdbc;
        this.transaccion = new TransactionTemplate(administradorTransacciones);
        this.transaccion.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    ResultadoEventoStripe registrarEventoStripe(
            String eventId, String eventType, String objectId, Instant recibidoEn) {
        validarEvento(eventId, eventType, objectId, recibidoEn);
        return transaccion.execute(estado -> {
            int filas = jdbc.update(
                    SQL_REGISTRAR_EVENTO_STRIPE,
                    eventId, eventType, objectId, Timestamp.from(recibidoEn), Timestamp.from(recibidoEn));
            if (filas == 1) {
                return ResultadoEventoStripe.NUEVO;
            }
            EventoPersistido existente = buscarEvento(eventId, true).orElseThrow(() ->
                    new DataAccessResourceFailureException("No se pudo leer el evento Stripe registrado."));
            if (!eventType.equals(existente.eventType()) || !objectId.equals(existente.objectId())) {
                throw new DataAccessResourceFailureException("El identificador de evento Stripe no coincide.");
            }
            return eventoTerminado(existente.estado())
                    ? ResultadoEventoStripe.DUPLICADO
                    : ResultadoEventoStripe.REINTENTAR;
        });
    }

    ResultadoActualizacionMembresia aplicarActualizacionStripe(ActualizacionStripe actualizacion) {
        validarActualizacion(actualizacion);
        return transaccion.execute(estado -> aplicarDentroDeTransaccion(actualizacion));
    }

    void marcarEventoStripePendiente(String eventId, Instant actualizadoEn) {
        validarId(eventId, "evt_");
        if (actualizadoEn == null) {
            throw new IllegalArgumentException("Se requiere la hora de reintento del evento.");
        }
        transaccion.executeWithoutResult(estado -> jdbc.update("""
                UPDATE stripe_evento_procesado
                SET estado = 'REINTENTAR', actualizado_en = ?
                WHERE event_id = ? AND estado IN ('RECIBIDO', 'REINTENTAR')
                """, Timestamp.from(actualizadoEn), eventId));
    }

    private ResultadoActualizacionMembresia aplicarDentroDeTransaccion(ActualizacionStripe actualizacion) {
        EventoPersistido evento = buscarEvento(actualizacion.eventId(), true).orElseThrow(() ->
                new DataAccessResourceFailureException("El evento Stripe todavía no está registrado."));
        if (!actualizacion.eventType().equals(evento.eventType())) {
            throw new DataAccessResourceFailureException("El tipo del evento Stripe no coincide.");
        }
        if (eventoTerminado(evento.estado())) {
            return new ResultadoActualizacionMembresia(false);
        }
        if (!actualizacion.aplicable()) {
            finalizarEvento(actualizacion, "IGNORADO");
            return new ResultadoActualizacionMembresia(false);
        }

        validarActualizacionAplicable(actualizacion, evento);
        bloquearCliente(actualizacion.clienteId());
        validarCustomer(actualizacion.clienteId(), actualizacion.customerId());
        ProyeccionVisible proyeccionAnterior = consultarProyeccionVisible(actualizacion.clienteId());
        if (actualizacion.sessionId() != null) {
            actualizarCheckout(actualizacion);
        }
        if (actualizacion.subscriptionId() != null) {
            guardarSuscripcion(actualizacion);
        }
        ProyeccionVisible proyeccionNueva = consultarProyeccionVisible(actualizacion.clienteId());
        finalizarEvento(actualizacion, "APLICADO");
        return new ResultadoActualizacionMembresia(!proyeccionAnterior.equals(proyeccionNueva));
    }

    private ProyeccionVisible consultarProyeccionVisible(UUID clienteId) {
        List<ProyeccionVisible> filas = jdbc.query(SQL_CONSULTAR_PROYECCION_VISIBLE,
                (rs, fila) -> new ProyeccionVisible(rs.getString("estado"),
                        instante(rs, "periodo_inicio"), instante(rs, "periodo_fin"),
                        instante(rs, "siguiente_cobro_en"), rs.getBoolean("cancelacion_al_final")), clienteId);
        return filas.stream().findFirst().orElseThrow(() ->
                new DataAccessResourceFailureException("No se encontró una cuenta CLIENTE para proyectar membresía."));
    }

    private void actualizarCheckout(ActualizacionStripe actualizacion) {
        if (!actualizacion.eventType().startsWith("checkout.session.")) {
            return;
        }
        if (actualizacion.intentoId() == null) {
            throw new DataAccessResourceFailureException("El evento Checkout no identifica el intento local.");
        }
        String estadoNuevo = "checkout.session.completed".equals(actualizacion.eventType())
                && actualizacion.subscriptionId() != null ? "COMPLETADO" : "RECONCILIANDO";
        List<EstadoSesionPersistida> filas = jdbc.query(
                SQL_BUSCAR_CHECKOUT_PARA_EVENTO,
                (rs, fila) -> new EstadoSesionPersistida(rs.getString("estado"), rs.getString("session_id")),
                actualizacion.intentoId(), actualizacion.clienteId());
        EstadoSesionPersistida actual = filas.stream().findFirst().orElseThrow(() ->
                new DataAccessResourceFailureException("No se encontró el intento del evento Checkout."));
        if (actual.sessionId() != null && !actualizacion.sessionId().equals(actual.sessionId())) {
            throw new DataAccessResourceFailureException("La sesión del evento no coincide con el intento local.");
        }
        if (actual.sessionId() != null && ("COMPLETADO".equals(actual.estado())
                || "EXPIRADO".equals(actual.estado()) || "FALLIDO".equals(actual.estado()))) {
            return;
        }
        int actualizados = jdbc.update(SQL_ACTUALIZAR_CHECKOUT_POR_EVENTO,
                estadoNuevo, actualizacion.sessionId(), Timestamp.from(actualizacion.recibidoEn()),
                actualizacion.intentoId(), actualizacion.clienteId(), actualizacion.sessionId());
        if (actualizados != 1) {
            throw new DataAccessResourceFailureException("No se pudo conciliar el intento Checkout.");
        }
    }

    private void guardarSuscripcion(ActualizacionStripe actualizacion) {
        exigirPrecio(actualizacion.priceId());
        String estadoLocal = mapearEstadoMembresia(
                actualizacion.estadoSuscripcionStripe(), actualizacion.estadoFacturaStripe());
        Instant eventoCreado = actualizacion.eventCreatedEn();
        Timestamp periodoInicio = timestamp(actualizacion.periodoInicio());
        Timestamp periodoFin = timestamp(actualizacion.periodoFin());
        Timestamp eventoMarca = Timestamp.from(eventoCreado);
        Timestamp recibidoMarca = Timestamp.from(actualizacion.recibidoEn());

        int insertadas = jdbc.update(
                SQL_INSERTAR_SUSCRIPCION_STRIPE,
                actualizacion.subscriptionId(), actualizacion.clienteId(), actualizacion.customerId(),
                actualizacion.priceId(), actualizacion.estadoSuscripcionStripe(), estadoLocal,
                actualizacion.invoiceId(), actualizacion.estadoFacturaStripe(), periodoInicio, periodoFin,
                actualizacion.cancelAtPeriodEnd(), eventoMarca, recibidoMarca);
        if (insertadas == 1) {
            return;
        }

        SuscripcionPersistida existente = buscarSuscripcion(actualizacion.subscriptionId()).orElseThrow(() ->
                new DataAccessResourceFailureException("No se pudo leer la suscripción Stripe actualizada."));
        if (!existente.clienteId().equals(actualizacion.clienteId())
                || !existente.customerId().equals(actualizacion.customerId())
                || !existente.priceId().equals(actualizacion.priceId())) {
            throw new DataAccessResourceFailureException("La suscripción Stripe ya pertenece a otra relación local.");
        }
        if (eventoCreado.isBefore(existente.eventoCreadoEn())) {
            return;
        }

        int actualizadas = jdbc.update(
                SQL_ACTUALIZAR_SUSCRIPCION_STRIPE,
                actualizacion.estadoSuscripcionStripe(), estadoLocal, actualizacion.invoiceId(),
                actualizacion.estadoFacturaStripe(), periodoInicio, periodoFin,
                actualizacion.cancelAtPeriodEnd(), eventoMarca, recibidoMarca,
                actualizacion.subscriptionId(), actualizacion.clienteId(), actualizacion.customerId(),
                actualizacion.priceId(), eventoMarca);
        if (actualizadas == 0 && !eventoCreado.isBefore(existente.eventoCreadoEn())) {
            throw new DataAccessResourceFailureException("No se pudo guardar el estado actual de la suscripción.");
        }
    }

    private Optional<SuscripcionPersistida> buscarSuscripcion(String subscriptionId) {
        List<SuscripcionPersistida> filas = jdbc.query(
                SQL_BUSCAR_SUSCRIPCION_STRIPE, (rs, fila) -> new SuscripcionPersistida(
                rs.getObject("cliente_id", UUID.class), rs.getString("stripe_customer_id"),
                rs.getString("price_id"), instante(rs, "evento_creado_en")), subscriptionId);
        return filas.stream().findFirst();
    }

    private void validarCustomer(UUID clienteId, String customerId) {
        List<String> filas = jdbc.query(
                SQL_VALIDAR_CUSTOMER_STRIPE,
                (rs, fila) -> rs.getString("stripe_customer_id"), clienteId, customerId);
        if (filas.isEmpty()) {
            throw new DataAccessResourceFailureException("El Customer Stripe no pertenece al cliente autenticado.");
        }
    }

    private void validarActualizacionAplicable(ActualizacionStripe actualizacion, EventoPersistido evento) {
        if (actualizacion.clienteId() == null || actualizacion.customerId() == null
                || actualizacion.priceId() == null || actualizacion.eventCreatedEn() == null) {
            throw new DataAccessResourceFailureException("El evento Stripe no contiene una relación verificable.");
        }
        exigirIdSiExiste(actualizacion.customerId(), "cus_");
        if (actualizacion.subscriptionId() != null) {
            exigirIdSiExiste(actualizacion.subscriptionId(), "sub_");
        }
        exigirPrecio(actualizacion.priceId());
        String objectId = objetoEvento(actualizacion);
        if (objectId == null || !objectId.equals(evento.objectId())) {
            throw new DataAccessResourceFailureException("El objeto del evento Stripe no coincide con el payload validado.");
        }
        if (actualizacion.eventType().startsWith("checkout.session.")
                && (actualizacion.sessionId() == null || actualizacion.intentoId() == null)) {
            throw new DataAccessResourceFailureException("El evento Checkout no contiene su intento y sesión.");
        }
        if (!actualizacion.eventType().startsWith("checkout.session.")
                && actualizacion.subscriptionId() == null) {
            throw new DataAccessResourceFailureException("El evento Stripe no contiene una suscripción.");
        }
    }

    private void finalizarEvento(ActualizacionStripe actualizacion, String estadoFinal) {
        Timestamp eventoCreado = timestamp(actualizacion.eventCreatedEn());
        Timestamp procesado = Timestamp.from(actualizacion.recibidoEn());
        int filas = jdbc.update(
                SQL_FINALIZAR_EVENTO_STRIPE,
                estadoFinal, eventoCreado, procesado, procesado, actualizacion.eventId());
        if (filas != 1) {
            throw new DataAccessResourceFailureException("No se pudo cerrar el evento Stripe.");
        }
    }

    private Optional<EventoPersistido> buscarEvento(String eventId, boolean bloquear) {
        String consulta = bloquear ? SQL_BUSCAR_EVENTO_PARA_ACTUALIZAR : SQL_BUSCAR_EVENTO_STRIPE;
        List<EventoPersistido> filas = jdbc.query(consulta, (rs, fila) -> new EventoPersistido(
                rs.getString("event_type"), rs.getString("object_id"), rs.getString("estado")), eventId);
        return filas.stream().findFirst();
    }

    private void bloquearCliente(UUID clienteId) {
        List<UUID> filas = jdbc.query(
                SQL_BLOQUEAR_CLIENTE_EVENTO_STRIPE,
                (rs, fila) -> rs.getObject("id", UUID.class), clienteId);
        if (filas.isEmpty()) {
            throw new DataAccessResourceFailureException("El evento no pertenece a una cuenta CLIENTE.");
        }
    }

    private static String objetoEvento(ActualizacionStripe actualizacion) {
        if (actualizacion.eventType().startsWith("checkout.session.")) {
            return actualizacion.sessionId();
        }
        if (actualizacion.eventType().startsWith("invoice.")) {
            return actualizacion.invoiceId();
        }
        return actualizacion.subscriptionId();
    }

    private static String mapearEstadoMembresia(String estadoStripe, String estadoFactura) {
        String estado = estadoStripe == null ? "" : estadoStripe.toLowerCase(Locale.ROOT);
        String factura = estadoFactura == null ? "" : estadoFactura.toLowerCase(Locale.ROOT);
        if ("canceled".equals(estado)) {
            return "CANCELADA";
        }
        if ("past_due".equals(estado) || "unpaid".equals(estado)
                || "open".equals(factura) || "uncollectible".equals(factura)
                || "payment_failed".equals(factura)) {
            return "PAGO_VENCIDO";
        }
        if ("incomplete".equals(estado) || "trialing".equals(estado)) {
            return "PENDIENTE";
        }
        if ("active".equals(estado)) {
            return "paid".equals(factura) ? "ACTIVA" : "PENDIENTE";
        }
        return "INACTIVA";
    }

    private static void validarActualizacion(ActualizacionStripe actualizacion) {
        if (actualizacion == null || actualizacion.eventId() == null
                || actualizacion.eventType() == null || actualizacion.recibidoEn() == null
                || !EVENTOS_PERMITIDOS.contains(actualizacion.eventType())) {
            throw new IllegalArgumentException("La actualización Stripe no es válida.");
        }
        validarId(actualizacion.eventId(), "evt_");
    }

    private static void validarEvento(String eventId, String eventType, String objectId, Instant recibidoEn) {
        validarId(eventId, "evt_");
        if (eventType == null || !EVENTOS_PERMITIDOS.contains(eventType)
                || objectId == null || !objectId.matches("[A-Za-z0-9_]+") || recibidoEn == null) {
            throw new IllegalArgumentException("El evento Stripe no es válido.");
        }
    }

    private static void validarId(String id, String prefijo) {
        exigirIdSiExiste(id, prefijo);
    }

    private static void exigirIdSiExiste(String id, String prefijo) {
        if (id == null || id.length() > 255 || !id.startsWith(prefijo)
                || !id.matches("[A-Za-z0-9_]+")) {
            throw new IllegalArgumentException("El identificador Stripe no es válido.");
        }
    }

    private static void exigirPrecio(String priceId) {
        if (!PRICE_ID.equals(priceId)) {
            throw new DataAccessResourceFailureException("La suscripción no usa el precio aprobado.");
        }
    }

    private static boolean eventoTerminado(String estado) {
        return "APLICADO".equals(estado) || "IGNORADO".equals(estado);
    }

    private static Instant instante(ResultSet rs, String columna) throws SQLException {
        Timestamp marca = rs.getTimestamp(columna);
        return marca == null ? null : marca.toInstant();
    }

    private static Timestamp timestamp(Instant instante) {
        return instante == null ? null : Timestamp.from(instante);
    }

    private record EventoPersistido(String eventType, String objectId, String estado) {
    }

    private record EstadoSesionPersistida(String estado, String sessionId) {
    }

    private record SuscripcionPersistida(UUID clienteId, String customerId, String priceId, Instant eventoCreadoEn) {
    }

    private record ProyeccionVisible(
            String estado,
            Instant periodoInicio,
            Instant periodoFin,
            Instant siguienteCobroEn,
            boolean cancelacionAlFinal) {
    }
}
