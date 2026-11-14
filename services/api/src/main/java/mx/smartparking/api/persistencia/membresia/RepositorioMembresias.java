package mx.smartparking.api.persistencia.membresia;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.clientes.membresia.modelo.ActualizacionStripe;

/** Define cómo guardar y consultar pagos, membresías y avisos recibidos de Stripe. */
public interface RepositorioMembresias {

    Optional<ClienteStripePersistido> consultarClienteStripe(UUID clienteId);

    ClienteStripePersistido reservarClienteStripe(UUID clienteId, Instant ahora);

    void asociarCustomer(UUID clienteId, String customerId, Instant ahora);

    void marcarClienteStripeIndeterminado(UUID clienteId, Instant ahora);

    ReservaCheckout reservarCheckout(UUID clienteId, String claveHash, String huella,
            String priceId, Instant ahora);

    void asociarSesionCheckout(UUID intentoId, String sessionId, Instant expiraEn, Instant ahora);

    void reconciliarCheckout(UUID intentoId, EstadoCheckoutPersistido estado, String sessionId,
            Instant expiraEn, boolean sinSuscripcionNoTerminal, Instant reconciliadoEn);

    Optional<IntentoCheckoutPersistido> consultarCheckout(UUID clienteId, UUID intentoId);

    Optional<IntentoCheckoutPersistido> consultarCheckoutPorClave(UUID clienteId, String claveHash);

    ResumenMembresiaPersistido consultarResumenMembresia(UUID clienteId);

    /**
     * Consulta la membresía del cliente mientras se confirma una entrada para mantener coherentes
     * ambos datos.
     */
    ResumenMembresiaPersistido consultarResumenParaAcceso(UUID clienteId);

    ResultadoEventoStripe registrarEventoStripe(String eventId, String eventType,
            String objectId, Instant recibidoEn);

    ResultadoActualizacionMembresia aplicarActualizacionStripe(ActualizacionStripe actualizacion);

    void marcarEventoStripePendiente(String eventId, Instant actualizadoEn);
}
