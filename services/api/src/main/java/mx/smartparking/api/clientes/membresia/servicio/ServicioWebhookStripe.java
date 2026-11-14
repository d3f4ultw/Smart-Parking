package mx.smartparking.api.clientes.membresia.servicio;

import com.stripe.exception.SignatureVerificationException;
import java.time.Clock;
import java.time.Instant;
import java.util.Set;
import java.util.UUID;
import mx.smartparking.api.clientes.configuracion.CatalogoMembresia;
import mx.smartparking.api.clientes.membresia.configuracion.StripeMembresiaPropiedades;
import mx.smartparking.api.clientes.membresia.modelo.ActualizacionStripe;
import mx.smartparking.api.eventos.PublicadorEventosClientes;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.persistencia.membresia.ClienteStripePersistido;
import mx.smartparking.api.persistencia.membresia.EstadoCheckoutPersistido;
import mx.smartparking.api.persistencia.membresia.IntentoCheckoutPersistido;
import mx.smartparking.api.persistencia.membresia.RepositorioMembresias;
import mx.smartparking.api.persistencia.membresia.ResultadoActualizacionMembresia;
import mx.smartparking.api.persistencia.membresia.ResultadoEventoStripe;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * Comprueba los avisos recibidos de Stripe y actualiza únicamente los pagos relacionados con un
 * cliente registrado.
 */
@Service
public class ServicioWebhookStripe {

    private static final Set<String> EVENTOS_PERMITIDOS = Set.of(
            "customer.subscription.created", "checkout.session.completed", "checkout.session.expired",
            "invoice.paid", "invoice.payment_failed", "customer.subscription.updated",
            "customer.subscription.deleted");
    private static final String METADATA_CLIENTE = "smartparking_cliente_id";
    private static final String METADATA_INTENTO = "smartparking_checkout_intento";
    private static final String METADATA_PRECIO = "smartparking_price_id";

    private final ProveedorStripeMembresia stripe;
    private final RepositorioMembresias repositorio;
    private final CatalogoMembresia catalogo;
    private final StripeMembresiaPropiedades propiedades;
    private final ObjectMapper json;
    private final Clock reloj;
    private final PublicadorEventosClientes publicadorEventos;

    @Autowired
    public ServicioWebhookStripe(
            ProveedorStripeMembresia stripe,
            RepositorioMembresias repositorio,
            CatalogoMembresia catalogo,
            StripeMembresiaPropiedades propiedades,
            ObjectMapper json,
            PublicadorEventosClientes publicadorEventos) {
        this(stripe, repositorio, catalogo, propiedades, json, Clock.systemUTC(), publicadorEventos);
    }

    ServicioWebhookStripe(
            ProveedorStripeMembresia stripe,
            RepositorioMembresias repositorio,
            CatalogoMembresia catalogo,
            StripeMembresiaPropiedades propiedades,
            ObjectMapper json,
            Clock reloj,
            PublicadorEventosClientes publicadorEventos) {
        this.stripe = stripe;
        this.repositorio = repositorio;
        this.catalogo = catalogo;
        this.propiedades = propiedades;
        this.json = json;
        this.reloj = reloj;
        this.publicadorEventos = publicadorEventos;
    }

    /**
     * Comprueba que el aviso original provenga de Stripe y aplica una sola vez cada cambio de pago
     * permitido.
     */
    public void procesar(byte[] cuerpoOriginal, String firma) throws SignatureVerificationException {
        if (cuerpoOriginal == null || cuerpoOriginal.length == 0 || firma == null || firma.isBlank()) {
            throw solicitudNoValida();
        }
        if (!propiedades.stripeDisponible() || !propiedades.webhookDisponible()) {
            throw servicioNoDisponible();
        }
        try {
            stripe.validarFirmaWebhook(cuerpoOriginal, firma, propiedades.webhookSecret());
        } catch (SignatureVerificationException excepcion) {
            throw excepcion;
        } catch (StripeMembresiaException excepcion) {
            throw servicioNoDisponible();
        }

        Evento evento = leerEvento(cuerpoOriginal);
        if (!EVENTOS_PERMITIDOS.contains(evento.tipo())) {
            return;
        }
        Instant recibidoEn = reloj.instant();
        ResultadoEventoStripe registro = repositorio.registrarEventoStripe(
                evento.id(), evento.tipo(), evento.objetoId(), recibidoEn);
        if (registro == ResultadoEventoStripe.DUPLICADO) {
            return;
        }
        try {
            ActualizacionStripe actualizacion = evento.livemode()
                    ? noAplicable(evento, recibidoEn)
                    : conciliar(evento, recibidoEn);
            ResultadoActualizacionMembresia resultado = repositorio.aplicarActualizacionStripe(actualizacion);
            if (actualizacion.aplicable() && resultado.cambioVisible()) {
                publicadorEventos.membresiaActualizada();
            }
        } catch (RuntimeException excepcion) {
            if (excepcion instanceof DataAccessException) {
                repositorio.marcarEventoStripePendiente(evento.id(), reloj.instant());
                throw servicioNoDisponible();
            }
            repositorio.marcarEventoStripePendiente(evento.id(), reloj.instant());
            throw servicioNoDisponible();
        }
    }

    private ActualizacionStripe conciliar(Evento evento, Instant recibidoEn) {
        return switch (evento.tipo()) {
            case "checkout.session.completed", "checkout.session.expired" ->
                    conciliarCheckout(evento, recibidoEn);
            case "customer.subscription.created", "customer.subscription.updated",
                    "customer.subscription.deleted" -> conciliarSuscripcion(evento, recibidoEn);
            case "invoice.paid", "invoice.payment_failed" -> conciliarFactura(evento, recibidoEn);
            default -> noAplicable(evento, recibidoEn);
        };
    }

    private ActualizacionStripe conciliarCheckout(Evento evento, Instant recibidoEn) {
        ProveedorStripeMembresia.CheckoutRemoto sesion = stripe.obtenerCheckout(evento.objetoId());
        UUID clienteId = uuid(metadata(sesion.metadata(), METADATA_CLIENTE));
        UUID intentoId = uuid(metadata(sesion.metadata(), METADATA_INTENTO));
        String priceId = metadata(sesion.metadata(), METADATA_PRECIO);
        if (!checkoutValido(evento, sesion, clienteId, intentoId, priceId)
                || !relacionClienteValida(clienteId, sesion.customerId())
                || !intentoValido(clienteId, intentoId, sesion.customerId(), priceId, sesion.id())) {
            return noAplicable(evento, recibidoEn);
        }

        repositorio.asociarSesionCheckout(intentoId, sesion.id(), sesion.expiraEn(), recibidoEn);
        if ("checkout.session.expired".equals(evento.tipo())) {
            if (!"expired".equals(sesion.estado())) {
                return noAplicable(evento, recibidoEn);
            }
            if (stripe.tieneSuscripcionNoTerminal(sesion.customerId())) {
                repositorio.reconciliarCheckout(intentoId, EstadoCheckoutPersistido.EXPIRADO,
                        sesion.id(), sesion.expiraEn(), false, recibidoEn);
                return noAplicable(evento, recibidoEn);
            }
            return new ActualizacionStripe(evento.id(), evento.tipo(), evento.creadoEn(), sesion.id(), intentoId,
                    sesion.customerId(), null, clienteId, priceId, null, null, null,
                    null, null, false, recibidoEn, true);
        }
        if (!"complete".equals(sesion.estado()) || sesion.subscriptionId() == null) {
            throw servicioNoDisponible();
        }
        ProveedorStripeMembresia.SuscripcionRemota suscripcion = stripe.obtenerSuscripcion(sesion.subscriptionId());
        if (suscripcion == null || !sesion.subscriptionId().equals(suscripcion.id())
                || !sesion.customerId().equals(suscripcion.customerId())
                || !clienteId.toString().equals(metadata(suscripcion.metadata(), METADATA_CLIENTE))
                || !intentoId.toString().equals(metadata(suscripcion.metadata(), METADATA_INTENTO))
                || !priceId.equals(metadata(suscripcion.metadata(), METADATA_PRECIO))) {
            return noAplicable(evento, recibidoEn);
        }
        ProveedorStripeMembresia.FacturaRemota factura = facturaMasReciente(suscripcion);
        if (!facturaValida(factura, suscripcion)) {
            return noAplicable(evento, recibidoEn);
        }
        return actualizacionSuscripcion(evento, recibidoEn, sesion, intentoId, clienteId, priceId, suscripcion, factura);
    }

    private ActualizacionStripe conciliarSuscripcion(Evento evento, Instant recibidoEn) {
        ProveedorStripeMembresia.SuscripcionRemota suscripcion = stripe.obtenerSuscripcion(evento.objetoId());
        if (suscripcion == null) {
            return noAplicable(evento, recibidoEn);
        }
        if (!evento.objetoId().equals(suscripcion.id())) {
            return noAplicable(evento, recibidoEn);
        }
        UUID clienteId = uuid(metadata(suscripcion.metadata(), METADATA_CLIENTE));
        UUID intentoId = uuid(metadata(suscripcion.metadata(), METADATA_INTENTO));
        String priceId = metadata(suscripcion.metadata(), METADATA_PRECIO);
        if (!suscripcionValida(suscripcion, clienteId, intentoId, priceId)
                || !relacionClienteValida(clienteId, suscripcion.customerId())
                || !intentoValido(clienteId, intentoId, suscripcion.customerId(), priceId, null)) {
            return noAplicable(evento, recibidoEn);
        }
        ProveedorStripeMembresia.FacturaRemota factura = facturaMasReciente(suscripcion);
        if (!facturaValida(factura, suscripcion)) {
            return noAplicable(evento, recibidoEn);
        }
        return actualizacionSuscripcion(evento, recibidoEn, null, intentoId, clienteId, priceId,
                suscripcion, factura);
    }

    private ActualizacionStripe conciliarFactura(Evento evento, Instant recibidoEn) {
        ProveedorStripeMembresia.FacturaRemota factura = stripe.obtenerFactura(evento.objetoId());
        if (factura == null || factura.livemode() || factura.subscriptionId() == null
                || !evento.objetoId().equals(factura.id())) {
            return noAplicable(evento, recibidoEn);
        }
        ProveedorStripeMembresia.SuscripcionRemota suscripcion = stripe.obtenerSuscripcion(factura.subscriptionId());
        UUID clienteId = uuid(metadata(suscripcion.metadata(), METADATA_CLIENTE));
        UUID intentoId = uuid(metadata(suscripcion.metadata(), METADATA_INTENTO));
        String priceId = metadata(suscripcion.metadata(), METADATA_PRECIO);
        if (!suscripcionValida(suscripcion, clienteId, intentoId, priceId)
                || !relacionClienteValida(clienteId, suscripcion.customerId())
                || !factura.subscriptionId().equals(suscripcion.id())
                || !factura.customerId().equals(suscripcion.customerId())
                || !intentoValido(clienteId, intentoId, suscripcion.customerId(), priceId, null)) {
            return noAplicable(evento, recibidoEn);
        }
        if ("invoice.paid".equals(evento.tipo()) && !"paid".equals(factura.estado())) {
            throw servicioNoDisponible();
        }
        return actualizacionSuscripcion(evento, recibidoEn, null, intentoId, clienteId, priceId,
                suscripcion, factura);
    }

    private ActualizacionStripe actualizacionSuscripcion(
            Evento evento,
            Instant recibidoEn,
            ProveedorStripeMembresia.CheckoutRemoto sesion,
            UUID intentoId,
            UUID clienteId,
            String priceId,
            ProveedorStripeMembresia.SuscripcionRemota suscripcion,
            ProveedorStripeMembresia.FacturaRemota factura) {
        if (!suscripcionValida(suscripcion, clienteId, intentoId, priceId)
                || !relacionClienteValida(clienteId, suscripcion.customerId())) {
            return noAplicable(evento, recibidoEn);
        }
        return new ActualizacionStripe(evento.id(), evento.tipo(), evento.creadoEn(),
                sesion == null ? null : sesion.id(), intentoId, suscripcion.customerId(), suscripcion.id(), clienteId,
                priceId, suscripcion.estado(), factura == null ? suscripcion.latestInvoiceId() : factura.id(),
                factura == null ? null : factura.estado(), suscripcion.periodoInicio(), suscripcion.periodoFin(),
                suscripcion.cancelacionAlFinal(), recibidoEn, true);
    }

    private ProveedorStripeMembresia.FacturaRemota facturaMasReciente(
            ProveedorStripeMembresia.SuscripcionRemota suscripcion) {
        return suscripcion.latestInvoiceId() == null ? null : stripe.obtenerFactura(suscripcion.latestInvoiceId());
    }

    private boolean checkoutValido(Evento evento, ProveedorStripeMembresia.CheckoutRemoto sesion,
            UUID clienteId, UUID intentoId, String priceId) {
        String estadoEsperado = evento.tipo().endsWith("completed") ? "complete" : "expired";
        return sesion != null && evento.objetoId().equals(sesion.id()) && !sesion.livemode()
                && "subscription".equals(sesion.mode()) && estadoEsperado.equals(sesion.estado())
                && clienteId != null && intentoId != null && catalogo.precioId().equals(priceId)
                && sesion.expiraEn() != null;
    }

    private boolean suscripcionValida(ProveedorStripeMembresia.SuscripcionRemota suscripcion,
            UUID clienteId, UUID intentoId, String priceId) {
        return suscripcion != null && !suscripcion.livemode() && suscripcion.id() != null
                && clienteId != null && intentoId != null && catalogo.precioId().equals(priceId)
                && catalogo.precioId().equals(suscripcion.priceId())
                && suscripcion.customerId() != null;
    }

    private boolean relacionClienteValida(UUID clienteId, String customerId) {
        return clienteId != null && customerId != null
                && repositorio.consultarClienteStripe(clienteId)
                        .filter(cliente -> "ASOCIADO".equals(cliente.estado()))
                        .map(ClienteStripePersistido::customerId)
                        .filter(customerId::equals).isPresent();
    }

    private boolean intentoValido(UUID clienteId, UUID intentoId, String customerId, String priceId, String sessionId) {
        if (clienteId == null || intentoId == null) {
            return false;
        }
        return repositorio.consultarCheckout(clienteId, intentoId)
                .filter(intento -> intento.clienteId().equals(clienteId) && priceId.equals(intento.priceId()))
                .filter(intento -> intento.sessionId() == null || sessionId == null
                        || sessionId.equals(intento.sessionId()))
                .isPresent() && relacionClienteValida(clienteId, customerId);
    }

    private static boolean facturaValida(
            ProveedorStripeMembresia.FacturaRemota factura,
            ProveedorStripeMembresia.SuscripcionRemota suscripcion) {
        return factura == null || !factura.livemode()
                && suscripcion.id().equals(factura.subscriptionId())
                && suscripcion.customerId().equals(factura.customerId());
    }

    private Evento leerEvento(byte[] cuerpoOriginal) {
        try {
            JsonNode raiz = json.readTree(cuerpoOriginal);
            JsonNode objeto = raiz.path("data").path("object");
            long creado = raiz.path("created").asLong(-1);
            if (!raiz.isObject() || !objeto.isObject() || creado < 0) {
                throw solicitudNoValida();
            }
            String id = texto(raiz.path("id"));
            String tipo = texto(raiz.path("type"));
            String objetoId = texto(objeto.path("id"));
            if (id == null || !id.startsWith("evt_") || tipo == null
                    || objetoId == null || !objetoId.matches("[A-Za-z0-9_]+")) {
                throw solicitudNoValida();
            }
            return new Evento(id, tipo, objetoId, Instant.ofEpochSecond(creado), raiz.path("livemode").asBoolean(true));
        } catch (tools.jackson.core.JacksonException | ArithmeticException excepcion) {
            throw solicitudNoValida();
        }
    }

    private ActualizacionStripe noAplicable(Evento evento, Instant recibidoEn) {
        return new ActualizacionStripe(evento.id(), evento.tipo(), evento.creadoEn(), null, null,
                null, null, null, null, null, null, null, null, null, false, recibidoEn, false);
    }

    private static UUID uuid(String valor) {
        try {
            return valor == null ? null : UUID.fromString(valor);
        } catch (IllegalArgumentException excepcion) {
            return null;
        }
    }

    private static String metadata(java.util.Map<String, String> metadata, String clave) {
        return metadata == null ? null : metadata.get(clave);
    }

    private static String texto(JsonNode nodo) {
        return nodo == null || nodo.isMissingNode() || nodo.isNull() ? null : nodo.asText(null);
    }

    private static ErrorConfiguracion solicitudNoValida() {
        return new ErrorConfiguracion(HttpStatus.BAD_REQUEST,
                "No pudimos validar el aviso de pago.", "WEBHOOK_NO_VALIDO");
    }

    private static ErrorConfiguracion servicioNoDisponible() {
        return new ErrorConfiguracion(HttpStatus.SERVICE_UNAVAILABLE,
                "No pudimos conciliar el aviso de pago. Stripe volverá a intentarlo.", "STRIPE_NO_DISPONIBLE");
    }

    private record Evento(String id, String tipo, String objetoId, Instant creadoEn, boolean livemode) {
    }
}
