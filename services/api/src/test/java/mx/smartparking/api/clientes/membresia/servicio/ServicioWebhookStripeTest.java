package mx.smartparking.api.clientes.membresia.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.stripe.exception.SignatureVerificationException;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.clientes.configuracion.CatalogoMembresia;
import mx.smartparking.api.clientes.membresia.configuracion.StripeMembresiaPropiedades;
import mx.smartparking.api.clientes.membresia.modelo.ActualizacionStripe;
import mx.smartparking.api.eventos.PublicadorEventosClientes;
import mx.smartparking.api.persistencia.membresia.ClienteStripePersistido;
import mx.smartparking.api.persistencia.membresia.EstadoCheckoutPersistido;
import mx.smartparking.api.persistencia.membresia.IntentoCheckoutPersistido;
import mx.smartparking.api.persistencia.membresia.RepositorioMembresias;
import mx.smartparking.api.persistencia.membresia.ResultadoActualizacionMembresia;
import mx.smartparking.api.persistencia.membresia.ResultadoEventoStripe;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import tools.jackson.databind.ObjectMapper;

class ServicioWebhookStripeTest {

    private static final Instant AHORA = Instant.parse("2026-10-27T12:00:00Z");
    private static final String PRECIO = "price_1USQ5HAqtHmR2qmyAWwUp5vy";
    private static final CatalogoMembresia CATALOGO = new CatalogoMembresia(
            "prod_VTMowkF8XuDWIR", PRECIO, "Smart Parking - Membresía Mensual", 39_900, "MXN", "month", 1);

    @Test
    void verificaFirmaAntesDeRegistrarEvento() throws Exception {
        ProveedorStripeMembresia stripe = mock(ProveedorStripeMembresia.class);
        RepositorioMembresias repositorio = repositorioMock();
        org.mockito.Mockito.doThrow(new SignatureVerificationException("firma", "firma-invalida"))
                .when(stripe).validarFirmaWebhook(any(byte[].class), anyString(), anyString());
        ServicioWebhookStripe servicio = servicio(stripe, repositorio);

        assertThrows(SignatureVerificationException.class,
                () -> servicio.procesar(evento("customer.subscription.updated", false), "firma-invalida"));

        verify(repositorio, never()).registrarEventoStripe(anyString(), anyString(), anyString(), any());
    }

    @Test
    void ignoraEventosFirmadosDeModoLiveSinConsultarSuscripcion() throws Exception {
        ProveedorStripeMembresia stripe = mock(ProveedorStripeMembresia.class);
        RepositorioMembresias repositorio = repositorioMock();
        PublicadorEventosClientes publicador = mock(PublicadorEventosClientes.class);
        when(repositorio.registrarEventoStripe("evt_prueba", "customer.subscription.updated", "sub_prueba", AHORA))
                .thenReturn(ResultadoEventoStripe.NUEVO);

        servicio(stripe, repositorio, publicador).procesar(evento("customer.subscription.updated", true), "firma");

        ArgumentCaptor<ActualizacionStripe> captor = ArgumentCaptor.forClass(ActualizacionStripe.class);
        verify(repositorio).aplicarActualizacionStripe(captor.capture());
        assertFalse(captor.getValue().aplicable());
        assertEquals("evt_prueba", captor.getValue().eventId());
        verify(stripe, never()).obtenerSuscripcion(anyString());
        verify(publicador, never()).membresiaActualizada();
    }

    @Test
    void conciliaLaSuscripcionConCustomerPriceEInvoiceActuales() throws Exception {
        ProveedorStripeMembresia stripe = mock(ProveedorStripeMembresia.class);
        RepositorioMembresias repositorio = repositorioMock();
        PublicadorEventosClientes publicador = mock(PublicadorEventosClientes.class);
        UUID clienteId = UUID.randomUUID();
        UUID intentoId = UUID.randomUUID();
        String customerId = "cus_prueba";
        String subscriptionId = "sub_prueba";
        when(repositorio.registrarEventoStripe("evt_prueba", "customer.subscription.updated", subscriptionId, AHORA))
                .thenReturn(ResultadoEventoStripe.NUEVO);
        when(repositorio.consultarClienteStripe(clienteId)).thenReturn(Optional.of(
                new ClienteStripePersistido(clienteId, customerId, "ASOCIADO", AHORA)));
        when(repositorio.consultarCheckout(clienteId, intentoId)).thenReturn(Optional.of(
                new IntentoCheckoutPersistido(intentoId, clienteId, EstadoCheckoutPersistido.COMPLETADO,
                        "cs_test_prueba", PRECIO, AHORA, AHORA)));
        when(stripe.obtenerSuscripcion(subscriptionId)).thenReturn(new ProveedorStripeMembresia.SuscripcionRemota(
                subscriptionId, customerId, "active", "in_prueba", AHORA.minusSeconds(60),
                AHORA.plusSeconds(3600), false, PRECIO, false,
                metadata(clienteId, intentoId, PRECIO)));
        when(stripe.obtenerFactura("in_prueba")).thenReturn(new ProveedorStripeMembresia.FacturaRemota(
                "in_prueba", customerId, subscriptionId, "paid", false));
        when(repositorio.aplicarActualizacionStripe(any())).thenReturn(new ResultadoActualizacionMembresia(true));

        servicio(stripe, repositorio, publicador).procesar(evento("customer.subscription.updated", false), "firma");

        ArgumentCaptor<ActualizacionStripe> captor = ArgumentCaptor.forClass(ActualizacionStripe.class);
        InOrder orden = org.mockito.Mockito.inOrder(repositorio, publicador);
        orden.verify(repositorio).aplicarActualizacionStripe(captor.capture());
        ActualizacionStripe actualizacion = captor.getValue();
        assertTrue(actualizacion.aplicable());
        assertEquals(clienteId, actualizacion.clienteId());
        assertEquals(customerId, actualizacion.customerId());
        assertEquals(PRECIO, actualizacion.priceId());
        assertEquals("paid", actualizacion.estadoFacturaStripe());
        assertEquals(subscriptionId, actualizacion.subscriptionId());
        orden.verify(publicador).membresiaActualizada();
    }

    @Test
    void noPublicaSiLaProyeccionNoCambioVisiblemente() throws Exception {
        ProveedorStripeMembresia stripe = mock(ProveedorStripeMembresia.class);
        RepositorioMembresias repositorio = repositorioMock();
        PublicadorEventosClientes publicador = mock(PublicadorEventosClientes.class);
        UUID clienteId = UUID.randomUUID();
        UUID intentoId = UUID.randomUUID();
        prepararSuscripcionValida(stripe, repositorio, clienteId, intentoId);

        servicio(stripe, repositorio, publicador).procesar(evento("customer.subscription.updated", false), "firma");

        verify(publicador, never()).membresiaActualizada();
    }

    @Test
    void eventoDuplicadoNoActualizaNiPublica() throws Exception {
        ProveedorStripeMembresia stripe = mock(ProveedorStripeMembresia.class);
        RepositorioMembresias repositorio = repositorioMock();
        PublicadorEventosClientes publicador = mock(PublicadorEventosClientes.class);
        when(repositorio.registrarEventoStripe("evt_prueba", "customer.subscription.updated", "sub_prueba", AHORA))
                .thenReturn(ResultadoEventoStripe.DUPLICADO);

        servicio(stripe, repositorio, publicador).procesar(evento("customer.subscription.updated", false), "firma");

        verify(repositorio, never()).aplicarActualizacionStripe(any());
        verify(publicador, never()).membresiaActualizada();
    }

    @Test
    void falloAlAplicarNoPublica() throws Exception {
        ProveedorStripeMembresia stripe = mock(ProveedorStripeMembresia.class);
        RepositorioMembresias repositorio = repositorioMock();
        PublicadorEventosClientes publicador = mock(PublicadorEventosClientes.class);
        when(repositorio.registrarEventoStripe("evt_prueba", "customer.subscription.updated", "sub_prueba", AHORA))
                .thenReturn(ResultadoEventoStripe.NUEVO);
        when(repositorio.aplicarActualizacionStripe(any())).thenThrow(new IllegalStateException("fallo de prueba"));

        assertThrows(RuntimeException.class,
                () -> servicio(stripe, repositorio, publicador)
                        .procesar(evento("customer.subscription.updated", true), "firma"));

        verify(publicador, never()).membresiaActualizada();
        verify(repositorio).marcarEventoStripePendiente("evt_prueba", AHORA);
    }

    @Test
    void noRegistraEventosFueraDeLaListaAprobada() throws Exception {
        ProveedorStripeMembresia stripe = mock(ProveedorStripeMembresia.class);
        RepositorioMembresias repositorio = repositorioMock();

        servicio(stripe, repositorio).procesar(evento("customer.created", false), "firma");

        verify(repositorio, never()).registrarEventoStripe(anyString(), anyString(), anyString(), any());
    }

    private static ServicioWebhookStripe servicio(
            ProveedorStripeMembresia stripe, RepositorioMembresias repositorio) {
        return servicio(stripe, repositorio, mock(PublicadorEventosClientes.class));
    }

    private static ServicioWebhookStripe servicio(
            ProveedorStripeMembresia stripe,
            RepositorioMembresias repositorio,
            PublicadorEventosClientes publicador) {
        return new ServicioWebhookStripe(stripe, repositorio, CATALOGO,
                new StripeMembresiaPropiedades("sk_test_demo", "whsec_demo", "http://localhost:3000",
                        "2026-08-26.dahlia"), new ObjectMapper(), Clock.fixed(AHORA, ZoneOffset.UTC), publicador);
    }

    private static RepositorioMembresias repositorioMock() {
        RepositorioMembresias repositorio = mock(RepositorioMembresias.class);
        when(repositorio.aplicarActualizacionStripe(any())).thenReturn(new ResultadoActualizacionMembresia(false));
        return repositorio;
    }

    private static void prepararSuscripcionValida(
            ProveedorStripeMembresia stripe,
            RepositorioMembresias repositorio,
            UUID clienteId,
            UUID intentoId) {
        when(repositorio.registrarEventoStripe("evt_prueba", "customer.subscription.updated", "sub_prueba", AHORA))
                .thenReturn(ResultadoEventoStripe.NUEVO);
        when(repositorio.consultarClienteStripe(clienteId)).thenReturn(Optional.of(
                new ClienteStripePersistido(clienteId, "cus_prueba", "ASOCIADO", AHORA)));
        when(repositorio.consultarCheckout(clienteId, intentoId)).thenReturn(Optional.of(
                new IntentoCheckoutPersistido(intentoId, clienteId, EstadoCheckoutPersistido.COMPLETADO,
                        "cs_test_prueba", PRECIO, AHORA, AHORA)));
        when(stripe.obtenerSuscripcion("sub_prueba")).thenReturn(new ProveedorStripeMembresia.SuscripcionRemota(
                "sub_prueba", "cus_prueba", "active", "in_prueba", AHORA.minusSeconds(60),
                AHORA.plusSeconds(3600), false, PRECIO, false, metadata(clienteId, intentoId, PRECIO)));
        when(stripe.obtenerFactura("in_prueba")).thenReturn(new ProveedorStripeMembresia.FacturaRemota(
                "in_prueba", "cus_prueba", "sub_prueba", "paid", false));
    }

    private static byte[] evento(String tipo, boolean livemode) {
        String cuerpo = """
                {"id":"evt_prueba","type":"%s","created":%d,"livemode":%s,
                  "data":{"object":{"id":"sub_prueba"}}}
                """.formatted(tipo, AHORA.getEpochSecond(), livemode);
        return cuerpo.getBytes(StandardCharsets.UTF_8);
    }

    private static Map<String, String> metadata(UUID clienteId, UUID intentoId, String priceId) {
        return Map.of("smartparking_cliente_id", clienteId.toString(),
                "smartparking_checkout_intento", intentoId.toString(),
                "smartparking_price_id", priceId);
    }
}
