package mx.smartparking.api.persistencia.membresia;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.function.Supplier;
import mx.smartparking.api.clientes.membresia.modelo.ActualizacionStripe;
import mx.smartparking.api.persistencia.CargadorSql;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

/** Guarda y consulta en la base de datos las cuentas de pago y las membresías de los clientes. */
@Repository
public class RepositorioMembresiasJdbc implements RepositorioMembresias {

    private static final String SQL_RESERVAR_CLIENTE_STRIPE =
            CargadorSql.cargar("membresias/reservar_cliente_stripe.sql");
    private static final String SQL_ASOCIAR_CUSTOMER =
            CargadorSql.cargar("membresias/asociar_customer_stripe.sql");
    private static final String SQL_MARCAR_CUSTOMER_INDETERMINADO =
            CargadorSql.cargar("membresias/marcar_customer_stripe_indeterminado.sql");
    private static final String SQL_RESERVAR_CHECKOUT =
            CargadorSql.cargar("membresias/reservar_checkout.sql");
    private static final String SQL_ACTUALIZAR_CHECKOUT =
            CargadorSql.cargar("membresias/actualizar_checkout.sql");
    private static final String SQL_ACTUALIZAR_EXPIRACION_CHECKOUT_TERMINAL =
            CargadorSql.cargar("membresias/actualizar_expiracion_checkout_terminal.sql");
    private static final String SQL_BUSCAR_CLIENTE_STRIPE =
            CargadorSql.cargar("membresias/buscar_cliente_stripe.sql");
    private static final String SQL_BUSCAR_CHECKOUT_POR_CLAVE =
            CargadorSql.cargar("membresias/buscar_checkout_por_clave.sql");
    private static final String SQL_LEER_HUELLA_CHECKOUT =
            CargadorSql.cargar("membresias/leer_huella_checkout.sql");
    private static final String SQL_EXISTE_MEMBRESIA_NO_TERMINAL =
            CargadorSql.cargar("membresias/existe_membresia_no_terminal.sql");
    private static final String SQL_CONTAR_INTENTOS_RECIENTES =
            CargadorSql.cargar("membresias/contar_intentos_checkout_recientes.sql");
    private static final String SQL_BUSCAR_PROPIETARIO_CHECKOUT =
            CargadorSql.cargar("membresias/buscar_propietario_checkout.sql");
    private static final String SQL_BUSCAR_CHECKOUT_PARA_ACTUALIZAR =
            CargadorSql.cargar("membresias/buscar_checkout_para_actualizar.sql");
    private static final String SQL_BLOQUEAR_CLIENTE_ACTIVO =
            CargadorSql.cargar("membresias/bloquear_cliente_activo.sql");
    private static final String SQL_BLOQUEAR_CLIENTE_REGISTRADO =
            CargadorSql.cargar("membresias/bloquear_cliente_registrado.sql");
    private static final String SQL_BUSCAR_CHECKOUT =
            CargadorSql.cargar("membresias/buscar_checkout.sql");
    private static final String SQL_BUSCAR_CHECKOUT_PENDIENTE =
            CargadorSql.cargar("membresias/buscar_checkout_pendiente.sql");

    private static final String PRICE_ID = "price_1USQ5HAqtHmR2qmyAWwUp5vy";
    private static final Duration VENTANA_INTENTOS = Duration.ofMinutes(15);
    private static final int MAXIMO_INTENTOS = 5;
    private static final RowMapper<ClienteStripePersistido> MAPA_CLIENTE = (rs, fila) ->
            new ClienteStripePersistido(
                    rs.getObject("cliente_id", UUID.class), rs.getString("stripe_customer_id"),
                    rs.getString("estado"), instante(rs, "actualizada_en"));

    private static final RowMapper<IntentoCheckoutPersistido> MAPA_CHECKOUT = (rs, fila) ->
            new IntentoCheckoutPersistido(
                    rs.getObject("intento_id", UUID.class), rs.getObject("cliente_id", UUID.class),
                    EstadoCheckoutPersistido.valueOf(rs.getString("estado")), rs.getString("session_id"),
                    rs.getString("price_id"), instante(rs, "expira_en"), instante(rs, "creado_en"));

    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaccion;
    private final TransactionTemplate transaccionLectura;
    private final RepositorioEventosStripeJdbc eventos;

    public RepositorioMembresiasJdbc(
            JdbcTemplate jdbc,
            PlatformTransactionManager administradorTransacciones) {
        this.jdbc = jdbc;
        this.transaccion = crearTransaccion(administradorTransacciones, false);
        this.transaccionLectura = crearTransaccion(administradorTransacciones, true);
        this.eventos = new RepositorioEventosStripeJdbc(jdbc, administradorTransacciones);
    }

    @Override
    public Optional<ClienteStripePersistido> consultarClienteStripe(UUID clienteId) {
        return ejecutar(transaccionLectura, () -> buscarClienteStripe(clienteId));
    }

    @Override
    public ClienteStripePersistido reservarClienteStripe(UUID clienteId, Instant ahora) {
        return ejecutar(transaccion, () -> {
            bloquearClienteActivo(clienteId);
            Timestamp marca = Timestamp.from(ahora);
            jdbc.update(SQL_RESERVAR_CLIENTE_STRIPE, clienteId, marca, marca);
            return buscarClienteStripe(clienteId).orElseThrow(() ->
                    new DataAccessResourceFailureException("No se pudo reservar el Stripe Customer del cliente."));
        });
    }

    @Override
    public void asociarCustomer(UUID clienteId, String customerId, Instant ahora) {
        exigirIdentificador(customerId, "cus_");
        ejecutar(transaccion, () -> {
            bloquearClienteRegistrado(clienteId);
            int filas = jdbc.update(SQL_ASOCIAR_CUSTOMER, customerId, Timestamp.from(ahora), clienteId, customerId);
            exigirUnaFila(filas, "El Stripe Customer no coincide con la reserva local.");
            return null;
        });
    }

    @Override
    public void marcarClienteStripeIndeterminado(UUID clienteId, Instant ahora) {
        java.util.Objects.requireNonNull(ahora, "Se requiere la hora del cambio de estado.");
        ejecutar(transaccion, () -> {
            bloquearClienteRegistrado(clienteId);
            int filas = jdbc.update(SQL_MARCAR_CUSTOMER_INDETERMINADO, clienteId);
            exigirUnaFila(filas, "No existe una reserva de Stripe Customer pendiente.");
            return null;
        });
    }

    @Override
    public ReservaCheckout reservarCheckout(UUID clienteId, String claveHash, String huella,
            String priceId, Instant ahora) {
        exigirHash(claveHash, "La clave idempotente no es válida.");
        exigirHash(huella, "La huella de solicitud no es válida.");
        if (!PRICE_ID.equals(priceId)) {
            throw new IllegalArgumentException("El precio solicitado no pertenece al catálogo aprobado.");
        }
        return ejecutar(transaccion, () -> {
            bloquearClienteActivo(clienteId);

            Optional<IntentoCheckoutPersistido> existente = buscarCheckoutPorClave(clienteId, claveHash);
            if (existente.isPresent()) {
                String huellaGuardada = leerHuellaCheckout(clienteId, claveHash);
                return new ReservaCheckout(
                        huella.equals(huellaGuardada)
                                ? EstadoReservaCheckout.REPLAY
                                : EstadoReservaCheckout.IDEMPOTENCIA_REUTILIZADA,
                        existente.get());
            }

            if (existeMembresiaNoTerminal(clienteId)) {
                return new ReservaCheckout(EstadoReservaCheckout.MEMBRESIA_NO_ELEGIBLE, null);
            }

            Optional<IntentoCheckoutPersistido> pendiente = buscarCheckoutPendiente(clienteId);
            if (pendiente.isPresent()) {
                return new ReservaCheckout(EstadoReservaCheckout.CHECKOUT_PENDIENTE, pendiente.get());
            }

            Instant limite = ahora.minus(VENTANA_INTENTOS);
            if (contarIntentosRecientes(clienteId, limite) >= MAXIMO_INTENTOS) {
                return new ReservaCheckout(EstadoReservaCheckout.LIMITE_ALCANZADO, null);
            }

            UUID intentoId = UUID.randomUUID();
            Timestamp marca = Timestamp.from(ahora);
            jdbc.update(SQL_RESERVAR_CHECKOUT, intentoId, clienteId, claveHash, huella, priceId, marca, marca);
            IntentoCheckoutPersistido nuevo = buscarCheckout(clienteId, intentoId).orElseThrow(() ->
                    new DataAccessResourceFailureException("No se pudo guardar el intento de Checkout."));
            return new ReservaCheckout(EstadoReservaCheckout.NUEVA, nuevo);
        });
    }

    @Override
    public void asociarSesionCheckout(UUID intentoId, String sessionId, Instant expiraEn, Instant ahora) {
        exigirIdentificador(sessionId, "cs_test_");
        if (expiraEn == null) {
            throw new IllegalArgumentException("La sesión Checkout debe tener fecha de expiración.");
        }
        ejecutar(transaccion, () -> {
            UUID clienteId = buscarPropietarioCheckout(intentoId).orElseThrow(() ->
                    new DataAccessResourceFailureException("No se encontró el intento de Checkout."));
            bloquearClienteRegistrado(clienteId);
            IntentoCheckoutPersistido actual = buscarCheckoutParaActualizar(clienteId, intentoId).orElseThrow(() ->
                    new DataAccessResourceFailureException("No se encontró el intento de Checkout."));
            if (actual.sessionId() != null && !sessionId.equals(actual.sessionId())) {
                throw new DataAccessResourceFailureException("La sesión Stripe no coincide con el intento local.");
            }
            if (actual.expiraEn() != null && !expiraEn.equals(actual.expiraEn())) {
                throw new DataAccessResourceFailureException("La expiración Stripe no coincide con el intento local.");
            }
            EstadoCheckoutPersistido estado = actual.estado();
            if (estado == EstadoCheckoutPersistido.RESERVADO || estado == EstadoCheckoutPersistido.INDETERMINADO) {
                estado = EstadoCheckoutPersistido.ABIERTO;
            }
            int filas = jdbc.update(
                    SQL_ACTUALIZAR_CHECKOUT,
                    estado.name(), sessionId, Timestamp.from(expiraEn), Timestamp.from(ahora), intentoId,
                    clienteId);
            if (filas != 1) {
                throw new DataAccessResourceFailureException("La sesión Stripe no coincide con el intento local.");
            }
            return null;
        });
    }

    @Override
    public void reconciliarCheckout(UUID intentoId, EstadoCheckoutPersistido estado, String sessionId,
            Instant expiraEn, boolean sinSuscripcionNoTerminal, Instant reconciliadoEn) {
        if (estado == null || estado == EstadoCheckoutPersistido.RESERVADO) {
            throw new IllegalArgumentException("El estado consultado de Checkout no es válido.");
        }
        if (sessionId != null) {
            exigirIdentificador(sessionId, "cs_test_");
        }
        ejecutar(transaccion, () -> {
            UUID clienteId = buscarPropietarioCheckout(intentoId).orElseThrow(() ->
                    new DataAccessResourceFailureException("No se encontró el intento de Checkout."));
            bloquearClienteRegistrado(clienteId);
            IntentoCheckoutPersistido actual = buscarCheckoutParaActualizar(clienteId, intentoId).orElseThrow(() ->
                    new DataAccessResourceFailureException("No se encontró el intento de Checkout."));
            if (sessionId != null && actual.sessionId() != null && !sessionId.equals(actual.sessionId())) {
                throw new DataAccessResourceFailureException("La sesión Stripe no coincide con el intento local.");
            }
            if (esTerminal(actual.estado())) {
                if (expiraEn != null && actual.expiraEn() == null) {
                    jdbc.update(
                            SQL_ACTUALIZAR_EXPIRACION_CHECKOUT_TERMINAL,
                            Timestamp.from(expiraEn), Timestamp.from(reconciliadoEn), intentoId, clienteId);
                }
                return null;
            }
            EstadoCheckoutPersistido estadoFinal = estado;
            if (estado == EstadoCheckoutPersistido.EXPIRADO && !sinSuscripcionNoTerminal) {
                estadoFinal = EstadoCheckoutPersistido.RECONCILIANDO;
            }
            String sessionFinal = sessionId == null ? actual.sessionId() : sessionId;
            Instant expiraFinal = expiraEn == null ? actual.expiraEn() : expiraEn;
            jdbc.update(SQL_ACTUALIZAR_CHECKOUT, estadoFinal.name(), sessionFinal, timestamp(expiraFinal),
                    Timestamp.from(reconciliadoEn), intentoId, clienteId);
            return null;
        });
    }

    @Override
    public Optional<IntentoCheckoutPersistido> consultarCheckout(UUID clienteId, UUID intentoId) {
        return ejecutar(transaccionLectura, () -> buscarCheckout(clienteId, intentoId));
    }

    @Override
    public Optional<IntentoCheckoutPersistido> consultarCheckoutPorClave(UUID clienteId, String claveHash) {
        exigirHash(claveHash, "La clave idempotente no es válida.");
        return ejecutar(transaccionLectura, () -> buscarCheckoutPorClave(clienteId, claveHash));
    }

    @Override
    public ResumenMembresiaPersistido consultarResumenMembresia(UUID clienteId) {
        return ejecutar(transaccionLectura, () -> ResumenMembresiaJdbc.consultar(jdbc, clienteId));
    }

    @Override
    @Transactional(propagation = Propagation.MANDATORY)
    public ResumenMembresiaPersistido consultarResumenParaAcceso(UUID clienteId) {
        // Los avisos de pago esperan a que terminen los otros cambios antes de modificar la membresía.
        bloquearClienteActivo(clienteId);
        return ResumenMembresiaJdbc.consultar(jdbc, clienteId);
    }

    @Override
    public ResultadoEventoStripe registrarEventoStripe(String eventId, String eventType,
            String objectId, Instant recibidoEn) {
        return eventos.registrarEventoStripe(eventId, eventType, objectId, recibidoEn);
    }

    @Override
    public ResultadoActualizacionMembresia aplicarActualizacionStripe(ActualizacionStripe actualizacion) {
        return eventos.aplicarActualizacionStripe(actualizacion);
    }

    @Override
    public void marcarEventoStripePendiente(String eventId, Instant actualizadoEn) {
        eventos.marcarEventoStripePendiente(eventId, actualizadoEn);
    }

    private Optional<ClienteStripePersistido> buscarClienteStripe(UUID clienteId) {
        List<ClienteStripePersistido> filas = jdbc.query(SQL_BUSCAR_CLIENTE_STRIPE, MAPA_CLIENTE, clienteId);
        return filas.stream().findFirst();
    }

    private Optional<IntentoCheckoutPersistido> buscarCheckout(UUID clienteId, UUID intentoId) {
        List<IntentoCheckoutPersistido> filas = jdbc.query(SQL_BUSCAR_CHECKOUT, MAPA_CHECKOUT, clienteId, intentoId);
        return filas.stream().findFirst();
    }

    private Optional<IntentoCheckoutPersistido> buscarCheckoutPorClave(UUID clienteId, String claveHash) {
        List<IntentoCheckoutPersistido> filas = jdbc.query(
                SQL_BUSCAR_CHECKOUT_POR_CLAVE, MAPA_CHECKOUT, clienteId, claveHash);
        return filas.stream().findFirst();
    }

    private Optional<IntentoCheckoutPersistido> buscarCheckoutParaActualizar(UUID clienteId, UUID intentoId) {
        List<IntentoCheckoutPersistido> filas = jdbc.query(SQL_BUSCAR_CHECKOUT_PARA_ACTUALIZAR, MAPA_CHECKOUT,
                clienteId, intentoId);
        return filas.stream().findFirst();
    }

    private Optional<UUID> buscarPropietarioCheckout(UUID intentoId) {
        List<UUID> filas = jdbc.query(SQL_BUSCAR_PROPIETARIO_CHECKOUT,
                (rs, fila) -> rs.getObject("cliente_id", UUID.class), intentoId);
        return filas.stream().findFirst();
    }

    private String leerHuellaCheckout(UUID clienteId, String claveHash) {
        String huella = jdbc.queryForObject(SQL_LEER_HUELLA_CHECKOUT, String.class, clienteId, claveHash);
        return huella == null ? "" : huella.trim();
    }

    private boolean existeMembresiaNoTerminal(UUID clienteId) {
        Integer filas = jdbc.queryForObject(SQL_EXISTE_MEMBRESIA_NO_TERMINAL, Integer.class, clienteId);
        return filas != null && filas > 0;
    }

    private Optional<IntentoCheckoutPersistido> buscarCheckoutPendiente(UUID clienteId) {
        List<IntentoCheckoutPersistido> filas = jdbc.query(SQL_BUSCAR_CHECKOUT_PENDIENTE, MAPA_CHECKOUT, clienteId);
        return filas.stream().findFirst();
    }

    private int contarIntentosRecientes(UUID clienteId, Instant limite) {
        Integer cantidad = jdbc.queryForObject(
                SQL_CONTAR_INTENTOS_RECIENTES, Integer.class, clienteId, Timestamp.from(limite));
        return cantidad == null ? 0 : cantidad;
    }

    private void bloquearClienteActivo(UUID clienteId) {
        bloquearCliente(clienteId, true);
    }

    private void bloquearClienteRegistrado(UUID clienteId) {
        bloquearCliente(clienteId, false);
    }

    private void bloquearCliente(UUID clienteId, boolean exigirActivo) {
        String consulta = exigirActivo ? SQL_BLOQUEAR_CLIENTE_ACTIVO : SQL_BLOQUEAR_CLIENTE_REGISTRADO;
        List<UUID> filas = jdbc.query(consulta,
                (rs, fila) -> rs.getObject("id", UUID.class), clienteId);
        if (filas.isEmpty()) {
            throw new DataAccessResourceFailureException("No se encontró una cuenta CLIENTE válida.");
        }
    }

    private static Instant instante(ResultSet rs, String columna) throws SQLException {
        Timestamp marca = rs.getTimestamp(columna);
        return marca == null ? null : marca.toInstant();
    }

    private static Timestamp timestamp(Instant instante) {
        return instante == null ? null : Timestamp.from(instante);
    }

    private static void exigirIdentificador(String valor, String prefijo) {
        if (valor == null || valor.length() > 255 || !valor.startsWith(prefijo)
                || !valor.matches("[A-Za-z0-9_]+")) {
            throw new IllegalArgumentException("El identificador Stripe no es válido.");
        }
    }

    private static void exigirHash(String hash, String mensaje) {
        if (hash == null || !hash.matches("[0-9a-f]{64}")) {
            throw new IllegalArgumentException(mensaje);
        }
    }

    private static void exigirUnaFila(int filas, String mensaje) {
        if (filas != 1) {
            throw new DataAccessResourceFailureException(mensaje);
        }
    }

    private static boolean esTerminal(EstadoCheckoutPersistido estado) {
        return estado == EstadoCheckoutPersistido.COMPLETADO
                || estado == EstadoCheckoutPersistido.EXPIRADO || estado == EstadoCheckoutPersistido.FALLIDO;
    }

    private static TransactionTemplate crearTransaccion(
            PlatformTransactionManager administradorTransacciones, boolean soloLectura) {
        TransactionTemplate plantilla = new TransactionTemplate(administradorTransacciones);
        plantilla.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        plantilla.setReadOnly(soloLectura);
        return plantilla;
    }

    private static <T> T ejecutar(TransactionTemplate plantilla, Supplier<T> operacion) {
        return plantilla.execute(estado -> operacion.get());
    }
}
