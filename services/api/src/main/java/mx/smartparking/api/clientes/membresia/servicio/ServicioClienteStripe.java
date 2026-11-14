package mx.smartparking.api.clientes.membresia.servicio;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.persistencia.membresia.ClienteStripePersistido;
import mx.smartparking.api.persistencia.membresia.RepositorioMembresias;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

/** Prepara o recupera la cuenta de prueba de Stripe que corresponde a cada cliente. */
@Service
public class ServicioClienteStripe {

    private static final String ESTADO_RESERVADO = "RESERVADO";
    private static final String ESTADO_INDETERMINADO = "INDETERMINADO";
    private static final Duration VENTANA_IDEMPOTENCIA = Duration.ofHours(23);
    private static final String CLAVE_METADATA_CLIENTE = "smartparking_cliente_id";

    private final RepositorioMembresias repositorio;
    private final ProveedorStripeMembresia stripe;
    private final Clock reloj;

    @Autowired
    public ServicioClienteStripe(RepositorioMembresias repositorio, ProveedorStripeMembresia stripe) {
        this(repositorio, stripe, Clock.systemUTC());
    }

    ServicioClienteStripe(RepositorioMembresias repositorio, ProveedorStripeMembresia stripe, Clock reloj) {
        this.repositorio = repositorio;
        this.stripe = stripe;
        this.reloj = reloj;
    }

    public String obtenerCustomerId(UUID clienteId) {
        Instant ahora = reloj.instant();
        ClienteStripePersistido reserva = repositorio.consultarClienteStripe(clienteId)
                .orElseGet(() -> repositorio.reservarClienteStripe(clienteId, ahora));
        if (reserva.customerId() != null && "ASOCIADO".equals(reserva.estado())) {
            return reserva.customerId();
        }
        if (!ESTADO_RESERVADO.equals(reserva.estado())
                && !ESTADO_INDETERMINADO.equals(reserva.estado())) {
            throw noDisponible();
        }

        List<ProveedorStripeMembresia.ClienteRemoto> encontrados = stripe.buscarClientes(clienteId);
        if (encontrados.size() > 1 || encontrados.stream().anyMatch(cliente -> !clienteValido(clienteId, cliente))) {
            marcarIndeterminado(clienteId, reserva.estado(), ahora);
            throw noDisponible();
        }
        if (!encontrados.isEmpty()) {
            String customerId = encontrados.getFirst().id();
            repositorio.asociarCustomer(clienteId, customerId, ahora);
            return customerId;
        }
        if (ESTADO_INDETERMINADO.equals(reserva.estado())) {
            throw noDisponible();
        }
        if (reserva.actualizadaEn() == null
                || Duration.between(reserva.actualizadaEn(), ahora).compareTo(VENTANA_IDEMPOTENCIA) >= 0) {
            repositorio.marcarClienteStripeIndeterminado(clienteId, ahora);
            throw noDisponible();
        }

        ProveedorStripeMembresia.ClienteRemoto creado = stripe.crearCliente(
                clienteId, "smartparking-customer-" + clienteId);
        if (!clienteValido(clienteId, creado)) {
            marcarIndeterminado(clienteId, reserva.estado(), reloj.instant());
            throw noDisponible();
        }
        repositorio.asociarCustomer(clienteId, creado.id(), reloj.instant());
        return creado.id();
    }

    private void marcarIndeterminado(UUID clienteId, String estado, Instant ahora) {
        if (ESTADO_RESERVADO.equals(estado)) {
            repositorio.marcarClienteStripeIndeterminado(clienteId, ahora);
        }
    }

    private static boolean clienteValido(UUID clienteId, ProveedorStripeMembresia.ClienteRemoto cliente) {
        return cliente != null && cliente.id() != null && cliente.id().matches("cus_[A-Za-z0-9_]+")
                && !cliente.livemode()
                && cliente.metadata() != null
                && clienteId.toString().equals(cliente.metadata().get(CLAVE_METADATA_CLIENTE));
    }

    private static ErrorConfiguracion noDisponible() {
        return new ErrorConfiguracion(HttpStatus.SERVICE_UNAVAILABLE,
                "No pudimos preparar el pago en este momento. Inténtalo más tarde.",
                "STRIPE_NO_DISPONIBLE");
    }
}
