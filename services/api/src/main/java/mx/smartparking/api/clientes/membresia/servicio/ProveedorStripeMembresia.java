package mx.smartparking.api.clientes.membresia.servicio;

import com.stripe.exception.SignatureVerificationException;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Describe las operaciones con Stripe que se necesitan para cobrar y consultar una membresía. */
public interface ProveedorStripeMembresia {

    ClienteRemoto crearCliente(UUID clienteId, String claveIdempotencia);

    List<ClienteRemoto> buscarClientes(UUID clienteId);

    CheckoutRemoto crearCheckout(
            UUID clienteId,
            UUID intentoId,
            String customerId,
            String priceId,
            String successUrl,
            String cancelUrl,
            String integrationIdentifier,
            String claveIdempotencia);

    CheckoutRemoto obtenerCheckout(String sessionId);

    List<CheckoutRemoto> buscarCheckouts(String customerId);

    SuscripcionRemota obtenerSuscripcion(String subscriptionId);

    FacturaRemota obtenerFactura(String invoiceId);

    boolean tieneSuscripcionNoTerminal(String customerId);

    void validarFirmaWebhook(byte[] cuerpoOriginal, String firma, String secreto)
            throws SignatureVerificationException;

    record ClienteRemoto(String id, boolean livemode, Map<String, String> metadata) {
    }

    record CheckoutRemoto(
            String id,
            String url,
            String estado,
            String mode,
            Instant expiraEn,
            String customerId,
            String subscriptionId,
            boolean livemode,
            Map<String, String> metadata) {
    }

    record SuscripcionRemota(
            String id,
            String customerId,
            String estado,
            String latestInvoiceId,
            Instant periodoInicio,
            Instant periodoFin,
            boolean cancelacionAlFinal,
            String priceId,
            boolean livemode,
            Map<String, String> metadata) {
    }

    record FacturaRemota(
            String id,
            String customerId,
            String subscriptionId,
            String estado,
            boolean livemode) {
    }
}
