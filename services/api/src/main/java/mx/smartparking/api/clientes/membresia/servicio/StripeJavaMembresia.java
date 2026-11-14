package mx.smartparking.api.clientes.membresia.servicio;

import com.stripe.StripeClient;
import com.stripe.exception.SignatureVerificationException;
import com.stripe.exception.StripeException;
import com.stripe.model.Customer;
import com.stripe.model.Invoice;
import com.stripe.model.StripeCollection;
import com.stripe.model.StripeSearchResult;
import com.stripe.model.Subscription;
import com.stripe.model.SubscriptionItem;
import com.stripe.model.checkout.Session;
import com.stripe.net.RequestOptions;
import com.stripe.param.CustomerCreateParams;
import com.stripe.param.CustomerSearchParams;
import com.stripe.param.SubscriptionListParams;
import com.stripe.param.checkout.SessionListParams;
import com.stripe.param.checkout.SessionCreateParams;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import mx.smartparking.api.clientes.membresia.configuracion.StripeMembresiaPropiedades;
import org.springframework.stereotype.Component;

/** Conecta las operaciones de membresía con Stripe para crear y consultar los pagos. */
@Component
public final class StripeJavaMembresia implements ProveedorStripeMembresia {

    private static final String CLAVE_METADATA_CLIENTE = "smartparking_cliente_id";
    private static final String CLAVE_METADATA_INTENTO = "smartparking_checkout_intento";
    private static final String CLAVE_METADATA_PRECIO = "smartparking_price_id";

    private final StripeMembresiaPropiedades propiedades;
    private final StripeClient cliente;

    public StripeJavaMembresia(StripeMembresiaPropiedades propiedades) {
        this.propiedades = propiedades;
        this.cliente = propiedades.stripeDisponible()
                ? StripeClient.builder().setApiKey(propiedades.apiKey()).setMaxNetworkRetries(1).build()
                : null;
    }

    @Override
    public ClienteRemoto crearCliente(UUID clienteId, String claveIdempotencia) {
        CustomerCreateParams parametros = CustomerCreateParams.builder()
                .putMetadata(CLAVE_METADATA_CLIENTE, clienteId.toString())
                .build();
        try {
            Customer clienteCreado = cliente().v1().customers().create(parametros, opciones(claveIdempotencia));
            return mapearCliente(clienteCreado);
        } catch (StripeException excepcion) {
            throw falloProveedor(excepcion);
        }
    }

    @Override
    public List<ClienteRemoto> buscarClientes(UUID clienteId) {
        CustomerSearchParams parametros = CustomerSearchParams.builder()
                .setQuery("metadata['" + CLAVE_METADATA_CLIENTE + "']:'" + clienteId + "'")
                .setLimit(2L)
                .build();
        try {
            StripeSearchResult<Customer> resultado = cliente().v1().customers().search(parametros, opcionesLectura());
            return resultado.getData().stream().map(StripeJavaMembresia::mapearCliente).toList();
        } catch (StripeException excepcion) {
            throw falloProveedor(excepcion);
        }
    }

    @Override
    public CheckoutRemoto crearCheckout(
            UUID clienteId,
            UUID intentoId,
            String customerId,
            String priceId,
            String successUrl,
            String cancelUrl,
            String integrationIdentifier,
            String claveIdempotencia) {
        SessionCreateParams.SubscriptionData datosSuscripcion = SessionCreateParams.SubscriptionData.builder()
                .putMetadata(CLAVE_METADATA_CLIENTE, clienteId.toString())
                .putMetadata(CLAVE_METADATA_INTENTO, intentoId.toString())
                .putMetadata(CLAVE_METADATA_PRECIO, priceId)
                .build();
        SessionCreateParams parametros = SessionCreateParams.builder()
                .setMode(SessionCreateParams.Mode.SUBSCRIPTION)
                .setCustomer(customerId)
                .setSuccessUrl(successUrl)
                .setCancelUrl(cancelUrl)
                .setIntegrationIdentifier(integrationIdentifier)
                .putMetadata(CLAVE_METADATA_CLIENTE, clienteId.toString())
                .putMetadata(CLAVE_METADATA_INTENTO, intentoId.toString())
                .putMetadata(CLAVE_METADATA_PRECIO, priceId)
                .setSubscriptionData(datosSuscripcion)
                .addLineItem(SessionCreateParams.LineItem.builder().setPrice(priceId).setQuantity(1L).build())
                .putExtraParam("allowed_payment_method_types", List.of("card"))
                .build();
        try {
            Session sesion = cliente().v1().checkout().sessions().create(parametros, opciones(claveIdempotencia));
            return mapearCheckout(sesion);
        } catch (StripeException excepcion) {
            throw falloProveedor(excepcion);
        }
    }

    @Override
    public CheckoutRemoto obtenerCheckout(String sessionId) {
        try {
            return mapearCheckout(cliente().v1().checkout().sessions().retrieve(sessionId, opcionesLectura()));
        } catch (StripeException excepcion) {
            throw falloProveedor(excepcion);
        }
    }

    @Override
    public List<CheckoutRemoto> buscarCheckouts(String customerId) {
        try {
            List<CheckoutRemoto> resultado = new java.util.ArrayList<>();
            for (SessionListParams.Status estado : List.of(SessionListParams.Status.OPEN,
                    SessionListParams.Status.COMPLETE, SessionListParams.Status.EXPIRED)) {
                resultado.addAll(listarCheckouts(customerId, estado));
            }
            return List.copyOf(resultado);
        } catch (StripeException excepcion) {
            throw falloProveedor(excepcion);
        }
    }

    @Override
    public SuscripcionRemota obtenerSuscripcion(String subscriptionId) {
        try {
            return mapearSuscripcion(cliente().v1().subscriptions().retrieve(subscriptionId, opcionesLectura()));
        } catch (StripeException excepcion) {
            throw falloProveedor(excepcion);
        }
    }

    @Override
    public FacturaRemota obtenerFactura(String invoiceId) {
        try {
            return mapearFactura(cliente().v1().invoices().retrieve(invoiceId, opcionesLectura()));
        } catch (StripeException excepcion) {
            throw falloProveedor(excepcion);
        }
    }

    @Override
    public boolean tieneSuscripcionNoTerminal(String customerId) {
        SubscriptionListParams parametros = SubscriptionListParams.builder()
                .setCustomer(customerId)
                .setStatus(SubscriptionListParams.Status.ALL)
                .setLimit(100L)
                .build();
        try {
            StripeCollection<Subscription> suscripciones = cliente().v1().subscriptions()
                    .list(parametros, opcionesLectura());
            return suscripciones.getHasMore()
                    || suscripciones.getData().stream().anyMatch(StripeJavaMembresia::noTerminal);
        } catch (StripeException excepcion) {
            throw falloProveedor(excepcion);
        }
    }

    @Override
    public void validarFirmaWebhook(byte[] cuerpoOriginal, String firma, String secreto)
            throws SignatureVerificationException {
        cliente().constructEvent(new String(cuerpoOriginal, StandardCharsets.UTF_8), firma, secreto);
    }

    private StripeClient cliente() {
        if (cliente == null) {
            throw new StripeMembresiaException("La integración Stripe Sandbox no está disponible.");
        }
        return cliente;
    }

    private List<CheckoutRemoto> listarCheckouts(String customerId, SessionListParams.Status estado)
            throws StripeException {
        SessionListParams parametros = SessionListParams.builder()
                .setCustomer(customerId)
                .setStatus(estado)
                .setLimit(100L)
                .build();
        StripeCollection<Session> sesiones = cliente().v1().checkout().sessions()
                .list(parametros, opcionesLectura());
        if (Boolean.TRUE.equals(sesiones.getHasMore())) {
            throw new StripeMembresiaException("La búsqueda de Checkout requiere una revisión manual.");
        }
        return sesiones.getData().stream().map(StripeJavaMembresia::mapearCheckout).toList();
    }

    private RequestOptions opciones(String claveIdempotencia) {
        RequestOptions.RequestOptionsBuilder constructor = RequestOptions.builder()
                .setIdempotencyKey(claveIdempotencia);
        RequestOptions.RequestOptionsBuilder.unsafeSetStripeVersionOverride(constructor, propiedades.apiVersion());
        return constructor.build();
    }

    private RequestOptions opcionesLectura() {
        RequestOptions.RequestOptionsBuilder constructor = RequestOptions.builder();
        RequestOptions.RequestOptionsBuilder.unsafeSetStripeVersionOverride(constructor, propiedades.apiVersion());
        return constructor.build();
    }

    private static ClienteRemoto mapearCliente(Customer customer) {
        return new ClienteRemoto(customer.getId(), Boolean.TRUE.equals(customer.getLivemode()), metadata(customer));
    }

    private static CheckoutRemoto mapearCheckout(Session session) {
        Instant expiraEn = session.getExpiresAt() == null ? null : Instant.ofEpochSecond(session.getExpiresAt());
        return new CheckoutRemoto(
                session.getId(), session.getUrl(), session.getStatus(), session.getMode(), expiraEn,
                session.getCustomer(), session.getSubscription(), Boolean.TRUE.equals(session.getLivemode()),
                metadata(session));
    }

    private static SuscripcionRemota mapearSuscripcion(Subscription subscription) {
        List<SubscriptionItem> articulos = subscription.getItems() == null
                ? List.of()
                : subscription.getItems().getData();
        SubscriptionItem articulo = articulos.size() == 1 ? articulos.getFirst() : null;
        Instant inicio = articulo == null || articulo.getCurrentPeriodStart() == null
                ? null
                : Instant.ofEpochSecond(articulo.getCurrentPeriodStart());
        Instant fin = articulo == null || articulo.getCurrentPeriodEnd() == null
                ? null
                : Instant.ofEpochSecond(articulo.getCurrentPeriodEnd());
        String priceId = articulo == null || articulo.getPrice() == null ? null : articulo.getPrice().getId();
        return new SuscripcionRemota(
                subscription.getId(), subscription.getCustomer(), subscription.getStatus(),
                subscription.getLatestInvoice(), inicio, fin,
                Boolean.TRUE.equals(subscription.getCancelAtPeriodEnd()), priceId,
                Boolean.TRUE.equals(subscription.getLivemode()), metadata(subscription));
    }

    private static FacturaRemota mapearFactura(Invoice invoice) {
        String subscriptionId = null;
        if (invoice.getParent() != null && invoice.getParent().getSubscriptionDetails() != null) {
            subscriptionId = invoice.getParent().getSubscriptionDetails().getSubscription();
        }
        return new FacturaRemota(invoice.getId(), invoice.getCustomer(), subscriptionId,
                invoice.getStatus(), Boolean.TRUE.equals(invoice.getLivemode()));
    }

    private static Map<String, String> metadata(com.stripe.model.StripeObject objeto) {
        if (objeto instanceof Customer customer) {
            return customer.getMetadata() == null ? Map.of() : Map.copyOf(customer.getMetadata());
        }
        if (objeto instanceof Session session) {
            return session.getMetadata() == null ? Map.of() : Map.copyOf(session.getMetadata());
        }
        if (objeto instanceof Subscription subscription) {
            return subscription.getMetadata() == null ? Map.of() : Map.copyOf(subscription.getMetadata());
        }
        return Map.of();
    }

    private static boolean noTerminal(Subscription subscription) {
        String estado = subscription.getStatus();
        return !"canceled".equals(estado) && !"incomplete_expired".equals(estado);
    }

    private static StripeMembresiaException falloProveedor(StripeException excepcion) {
        return new StripeMembresiaException("Stripe Sandbox no respondió a la operación.", excepcion);
    }
}
