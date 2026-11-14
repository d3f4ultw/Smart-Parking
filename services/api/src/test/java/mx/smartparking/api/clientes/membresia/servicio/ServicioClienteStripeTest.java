package mx.smartparking.api.clientes.membresia.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.persistencia.membresia.ClienteStripePersistido;
import mx.smartparking.api.persistencia.membresia.RepositorioMembresias;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

class ServicioClienteStripeTest {

    private static final Instant AHORA = Instant.parse("2026-10-27T12:00:00Z");

    @Test
    void recuperaCustomerSandboxPorMetadataAntesDeCrearOtro() {
        RepositorioMembresias repositorio = mock(RepositorioMembresias.class);
        ProveedorStripeMembresia stripe = mock(ProveedorStripeMembresia.class);
        UUID clienteId = UUID.randomUUID();
        ClienteStripePersistido reserva = new ClienteStripePersistido(clienteId, null, "INDETERMINADO", AHORA);
        ProveedorStripeMembresia.ClienteRemoto remoto = clienteRemoto(clienteId, "cus_prueba");
        when(repositorio.consultarClienteStripe(clienteId)).thenReturn(Optional.of(reserva));
        when(stripe.buscarClientes(clienteId)).thenReturn(List.of(remoto));

        String customerId = new ServicioClienteStripe(repositorio, stripe, reloj()).obtenerCustomerId(clienteId);

        assertEquals("cus_prueba", customerId);
        verify(repositorio).asociarCustomer(clienteId, "cus_prueba", AHORA);
        verify(stripe, never()).crearCliente(clienteId, "smartparking-customer-" + clienteId);
    }

    @Test
    void creaCustomerConClaveDeterministaYAsociaDespuesDeLaRespuesta() {
        RepositorioMembresias repositorio = mock(RepositorioMembresias.class);
        ProveedorStripeMembresia stripe = mock(ProveedorStripeMembresia.class);
        UUID clienteId = UUID.randomUUID();
        when(repositorio.consultarClienteStripe(clienteId)).thenReturn(Optional.empty());
        when(repositorio.reservarClienteStripe(clienteId, AHORA))
                .thenReturn(new ClienteStripePersistido(clienteId, null, "RESERVADO", AHORA));
        when(stripe.buscarClientes(clienteId)).thenReturn(List.of());
        when(stripe.crearCliente(clienteId, "smartparking-customer-" + clienteId))
                .thenReturn(clienteRemoto(clienteId, "cus_prueba"));

        String customerId = new ServicioClienteStripe(repositorio, stripe, reloj()).obtenerCustomerId(clienteId);

        assertEquals("cus_prueba", customerId);
        verify(repositorio).asociarCustomer(clienteId, "cus_prueba", AHORA);
    }

    @Test
    void cierraEnEstadoIndeterminadoAlTerminarLaVentanaSinCustomerEncontrado() {
        RepositorioMembresias repositorio = mock(RepositorioMembresias.class);
        ProveedorStripeMembresia stripe = mock(ProveedorStripeMembresia.class);
        UUID clienteId = UUID.randomUUID();
        Instant reservaAntigua = AHORA.minusSeconds(23 * 60 * 60L);
        when(repositorio.consultarClienteStripe(clienteId)).thenReturn(Optional.of(
                new ClienteStripePersistido(clienteId, null, "RESERVADO", reservaAntigua)));
        when(stripe.buscarClientes(clienteId)).thenReturn(List.of());

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> new ServicioClienteStripe(repositorio, stripe, reloj()).obtenerCustomerId(clienteId));

        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, error.estadoHttp());
        verify(repositorio).marcarClienteStripeIndeterminado(clienteId, AHORA);
        verify(stripe, never()).crearCliente(clienteId, "smartparking-customer-" + clienteId);
    }

    private static ProveedorStripeMembresia.ClienteRemoto clienteRemoto(UUID clienteId, String customerId) {
        return new ProveedorStripeMembresia.ClienteRemoto(
                customerId, false, Map.of("smartparking_cliente_id", clienteId.toString()));
    }

    private static Clock reloj() {
        return Clock.fixed(AHORA, ZoneOffset.UTC);
    }
}
