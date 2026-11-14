package mx.smartparking.api.clientes.membresia.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.clientes.configuracion.CatalogoMembresia;
import mx.smartparking.api.clientes.membresia.configuracion.StripeMembresiaPropiedades;
import mx.smartparking.api.clientes.membresia.modelo.ResultadoInicioCheckout;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.persistencia.membresia.EstadoCheckoutPersistido;
import mx.smartparking.api.persistencia.membresia.EstadoReservaCheckout;
import mx.smartparking.api.persistencia.membresia.IntentoCheckoutPersistido;
import mx.smartparking.api.persistencia.membresia.RepositorioMembresias;
import mx.smartparking.api.persistencia.membresia.ReservaCheckout;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpStatus;

class ServicioCheckoutMembresiaTest {

    private static final Instant AHORA = Instant.parse("2026-10-27T12:00:00Z");
    private static final String PRECIO = "price_1USQ5HAqtHmR2qmyAWwUp5vy";
    private static final CatalogoMembresia CATALOGO = new CatalogoMembresia(
            "prod_VTMowkF8XuDWIR", PRECIO, "Smart Parking - Membresía Mensual", 39_900, "MXN", "month", 1);

    @Test
    void creaCheckoutConPrecioServidorOrigenLocalEIdempotenciaDerivada() {
        RepositorioMembresias repositorio = mock(RepositorioMembresias.class);
        ProveedorStripeMembresia stripe = mock(ProveedorStripeMembresia.class);
        ServicioClienteStripe clientes = mock(ServicioClienteStripe.class);
        StripeMembresiaPropiedades propiedades = propiedades();
        UUID clienteId = UUID.randomUUID();
        UUID intentoId = UUID.randomUUID();
        String customerId = "cus_prueba";
        IntentoCheckoutPersistido intento = intento(clienteId, intentoId, null, EstadoCheckoutPersistido.RESERVADO);
        when(repositorio.reservarCheckout(eq(clienteId), anyString(), anyString(), eq(PRECIO), eq(AHORA)))
                .thenReturn(new ReservaCheckout(EstadoReservaCheckout.NUEVA, intento));
        when(clientes.obtenerCustomerId(clienteId)).thenReturn(customerId);
        when(stripe.crearCheckout(eq(clienteId), eq(intentoId), eq(customerId), eq(PRECIO),
                anyString(), anyString(), anyString(), anyString()))
                .thenAnswer(llamada -> new ProveedorStripeMembresia.CheckoutRemoto(
                        "cs_test_prueba", "https://checkout.stripe.com/c/pay/cs_test_prueba", "open", "subscription",
                        AHORA.plusSeconds(3600), customerId, null, false,
                        Map.of("smartparking_cliente_id", clienteId.toString(),
                                "smartparking_checkout_intento", intentoId.toString(),
                                "smartparking_price_id", PRECIO)));
        when(repositorio.consultarCheckout(clienteId, intentoId)).thenReturn(Optional.of(
                intento(clienteId, intentoId, "cs_test_prueba", EstadoCheckoutPersistido.ABIERTO)));

        ResultadoInicioCheckout resultado = new ServicioCheckoutMembresia(
                repositorio, stripe, clientes, CATALOGO, propiedades, reloj())
                .iniciar(clienteId, "cliente-request-identifier-42");

        assertTrue(resultado.nuevo());
        assertEquals("https://checkout.stripe.com/c/pay/cs_test_prueba", resultado.respuesta().checkoutUrl());
        assertEquals("ABIERTO", resultado.respuesta().estado());
        ArgumentCaptor<String> successUrl = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> cancelUrl = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> integrationId = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> stripeKey = ArgumentCaptor.forClass(String.class);
        verify(stripe).crearCheckout(eq(clienteId), eq(intentoId), eq(customerId), eq(PRECIO),
                successUrl.capture(), cancelUrl.capture(), integrationId.capture(), stripeKey.capture());
        assertEquals("http://localhost:3100/clientes/checkout/retorno?intentoId=" + intentoId,
                successUrl.getValue());
        assertEquals(successUrl.getValue() + "&resultado=cancelado", cancelUrl.getValue());
        assertTrue(integrationId.getValue().matches("smartparking-[a-z]{8}"));
        assertEquals("smartparking-checkout-" + intentoId, stripeKey.getValue());
        verify(repositorio).asociarSesionCheckout(eq(intentoId), eq("cs_test_prueba"),
                eq(AHORA.plusSeconds(3600)), eq(AHORA));
    }

    @Test
    void rechazaClaveIdempotenteInvalidaAntesDeReservar() {
        RepositorioMembresias repositorio = mock(RepositorioMembresias.class);
        ProveedorStripeMembresia stripe = mock(ProveedorStripeMembresia.class);
        ServicioClienteStripe clientes = mock(ServicioClienteStripe.class);
        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> new ServicioCheckoutMembresia(repositorio, stripe, clientes, CATALOGO,
                        propiedades(), reloj()).iniciar(UUID.randomUUID(), "bad key"));

        assertEquals(HttpStatus.BAD_REQUEST, error.estadoHttp());
        verify(repositorio, org.mockito.Mockito.never())
                .reservarCheckout(org.mockito.ArgumentMatchers.any(), anyString(), anyString(), anyString(),
                        org.mockito.ArgumentMatchers.any());
    }

    private static IntentoCheckoutPersistido intento(
            UUID clienteId, UUID intentoId, String sessionId, EstadoCheckoutPersistido estado) {
        return new IntentoCheckoutPersistido(intentoId, clienteId, estado, sessionId, PRECIO,
                sessionId == null ? null : AHORA.plusSeconds(3600), AHORA);
    }

    private static StripeMembresiaPropiedades propiedades() {
        return new StripeMembresiaPropiedades("sk_test_demo", "whsec_demo", "http://localhost:3100",
                "2026-08-26.dahlia");
    }

    private static Clock reloj() {
        return Clock.fixed(AHORA, ZoneOffset.UTC);
    }
}
