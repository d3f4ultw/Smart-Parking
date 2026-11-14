package mx.smartparking.api.clientes.membresia.servicio;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.clientes.configuracion.CatalogoMembresia;
import mx.smartparking.api.clientes.membresia.configuracion.StripeMembresiaPropiedades;
import mx.smartparking.api.clientes.membresia.modelo.RespuestaCheckoutMembresia;
import mx.smartparking.api.clientes.membresia.modelo.RespuestaEstadoCheckoutMembresia;
import mx.smartparking.api.clientes.membresia.modelo.ResultadoInicioCheckout;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.persistencia.membresia.EstadoCheckoutPersistido;
import mx.smartparking.api.persistencia.membresia.EstadoReservaCheckout;
import mx.smartparking.api.persistencia.membresia.IntentoCheckoutPersistido;
import mx.smartparking.api.persistencia.membresia.RepositorioMembresias;
import mx.smartparking.api.persistencia.membresia.ReservaCheckout;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

/** Prepara el pago del plan autorizado y evita crear otro pago cuando se repite la misma solicitud. */
@Service
public class ServicioCheckoutMembresia {

    private static final String CLAVE_METADATA_CLIENTE = "smartparking_cliente_id";
    private static final String CLAVE_METADATA_INTENTO = "smartparking_checkout_intento";
    private static final String CLAVE_METADATA_PRECIO = "smartparking_price_id";
    private static final Duration VENTANA_IDEMPOTENCIA = Duration.ofHours(23);
    private static final String HUELLA_OPERACION = "subscription:quantity-1:card-only:v1";

    private final RepositorioMembresias repositorio;
    private final ProveedorStripeMembresia stripe;
    private final ServicioClienteStripe clientesStripe;
    private final CatalogoMembresia catalogo;
    private final StripeMembresiaPropiedades propiedades;
    private final Clock reloj;

    @Autowired
    public ServicioCheckoutMembresia(
            RepositorioMembresias repositorio,
            ProveedorStripeMembresia stripe,
            ServicioClienteStripe clientesStripe,
            CatalogoMembresia catalogo,
            StripeMembresiaPropiedades propiedades) {
        this(repositorio, stripe, clientesStripe, catalogo, propiedades, Clock.systemUTC());
    }

    ServicioCheckoutMembresia(
            RepositorioMembresias repositorio,
            ProveedorStripeMembresia stripe,
            ServicioClienteStripe clientesStripe,
            CatalogoMembresia catalogo,
            StripeMembresiaPropiedades propiedades,
            Clock reloj) {
        this.repositorio = repositorio;
        this.stripe = stripe;
        this.clientesStripe = clientesStripe;
        this.catalogo = catalogo;
        this.propiedades = propiedades;
        this.reloj = reloj;
    }

    /** Prepara el intento de pago y recupera el anterior si se vuelve a enviar la misma solicitud. */
    public ResultadoInicioCheckout iniciar(UUID clienteId, String claveIdempotencia) {
        exigirStripeDisponible();
        String clave = validarClave(claveIdempotencia);
        Instant ahora = reloj.instant();
        ReservaCheckout reserva = repositorio.reservarCheckout(
                clienteId, hash(clave), hash(HUELLA_OPERACION + ":" + catalogo.precioId()),
                catalogo.precioId(), ahora);
        IntentoCheckoutPersistido intento = validarReserva(reserva);
        if (esTerminal(intento.estado())) {
            throw conflicto("CHECKOUT_NO_DISPONIBLE", "Este enlace de pago ya no está disponible.");
        }
        ProveedorStripeMembresia.CheckoutRemoto sesion = obtenerOCrearSesion(clienteId, intento, ahora);
        if (!"open".equals(sesion.estado())) {
            throw conflicto("CHECKOUT_NO_DISPONIBLE", "Este enlace de pago ya no está disponible.");
        }
        return new ResultadoInicioCheckout(reserva.resultado() == EstadoReservaCheckout.NUEVA,
                new RespuestaCheckoutMembresia(intento.intentoId(), estadoActual(clienteId, intento.intentoId()),
                        sesion.url(), sesion.expiraEn()));
    }

    /** Consulta cómo va el pago y actualiza la información guardada con la respuesta de Stripe. */
    public RespuestaEstadoCheckoutMembresia consultar(UUID clienteId, UUID intentoId) {
        exigirStripeDisponible();
        IntentoCheckoutPersistido intento = repositorio.consultarCheckout(clienteId, intentoId)
                .orElseThrow(() -> new ErrorConfiguracion(HttpStatus.NOT_FOUND,
                        "No encontramos este intento de pago.", "CHECKOUT_NO_ENCONTRADO"));
        if (esTerminal(intento.estado()) && intento.sessionId() == null) {
            return respuestaEstado(intento, null);
        }
        if (intento.sessionId() == null) {
            ProveedorStripeMembresia.CheckoutRemoto sesion = buscarSesionPorMetadata(clienteId, intento, reloj.instant());
            if (sesion == null) {
                return respuestaEstado(intento, null);
            }
            return respuestaEstado(intento, reconciliarSesion(intento, sesion));
        }
        ProveedorStripeMembresia.CheckoutRemoto sesion = stripe.obtenerCheckout(intento.sessionId());
        validarSesion(clienteId, intento, sesion, clientesStripe.obtenerCustomerId(clienteId));
        return respuestaEstado(intento, reconciliarSesion(intento, sesion));
    }

    private ProveedorStripeMembresia.CheckoutRemoto obtenerOCrearSesion(
            UUID clienteId, IntentoCheckoutPersistido intento, Instant ahora) {
        if (intento.sessionId() != null) {
            ProveedorStripeMembresia.CheckoutRemoto existente = stripe.obtenerCheckout(intento.sessionId());
            validarSesion(clienteId, intento, existente, clientesStripe.obtenerCustomerId(clienteId));
            return reconciliarSesion(intento, existente);
        }
        String customerId = clientesStripe.obtenerCustomerId(clienteId);
        if (Duration.between(intento.creadoEn(), ahora).compareTo(VENTANA_IDEMPOTENCIA) >= 0) {
            ProveedorStripeMembresia.CheckoutRemoto recuperado = buscarSesionPorMetadata(
                    clienteId, intento, ahora, customerId);
            if (recuperado != null) {
                repositorio.asociarSesionCheckout(intento.intentoId(), recuperado.id(), recuperado.expiraEn(), ahora);
                return reconciliarSesion(intento, recuperado);
            }
            throw servicioNoDisponible();
        }

        String retorno = propiedades.webBaseUrl() + "/clientes/checkout/retorno?intentoId=" + intento.intentoId();
        String cancelar = retorno + "&resultado=cancelado";
        ProveedorStripeMembresia.CheckoutRemoto creada = stripe.crearCheckout(
                clienteId, intento.intentoId(), customerId, catalogo.precioId(), retorno, cancelar,
                integrationIdentifier(intento.intentoId()), "smartparking-checkout-" + intento.intentoId());
        validarSesion(clienteId, intento, creada, customerId);
        repositorio.asociarSesionCheckout(intento.intentoId(), creada.id(), creada.expiraEn(), reloj.instant());
        return reconciliarSesion(intento, creada);
    }

    private ProveedorStripeMembresia.CheckoutRemoto buscarSesionPorMetadata(
            UUID clienteId, IntentoCheckoutPersistido intento, Instant ahora) {
        String customerId = clientesStripe.obtenerCustomerId(clienteId);
        return buscarSesionPorMetadata(clienteId, intento, ahora, customerId);
    }

    private ProveedorStripeMembresia.CheckoutRemoto buscarSesionPorMetadata(
            UUID clienteId, IntentoCheckoutPersistido intento, Instant ahora, String customerId) {
        List<ProveedorStripeMembresia.CheckoutRemoto> encontradas = stripe.buscarCheckouts(customerId).stream()
                .filter(sesion -> intento.intentoId().toString().equals(metadata(sesion, CLAVE_METADATA_INTENTO)))
                .toList();
        if (encontradas.size() > 1) {
            repositorio.reconciliarCheckout(intento.intentoId(), EstadoCheckoutPersistido.INDETERMINADO,
                    null, null, false, ahora);
            throw servicioNoDisponible();
        }
        if (encontradas.isEmpty()) {
            if (Duration.between(intento.creadoEn(), ahora).compareTo(VENTANA_IDEMPOTENCIA) >= 0) {
                repositorio.reconciliarCheckout(intento.intentoId(), EstadoCheckoutPersistido.INDETERMINADO,
                        null, null, false, ahora);
            }
            return null;
        }
        ProveedorStripeMembresia.CheckoutRemoto sesion = encontradas.getFirst();
        validarSesion(clienteId, intento, sesion, customerId);
        return sesion;
    }

    private ProveedorStripeMembresia.CheckoutRemoto reconciliarSesion(
            IntentoCheckoutPersistido intento, ProveedorStripeMembresia.CheckoutRemoto sesion) {
        Instant ahora = reloj.instant();
        if ("open".equals(sesion.estado())) {
            repositorio.reconciliarCheckout(intento.intentoId(), EstadoCheckoutPersistido.ABIERTO,
                    sesion.id(), sesion.expiraEn(), false, ahora);
        } else if ("complete".equals(sesion.estado())) {
            repositorio.reconciliarCheckout(intento.intentoId(), EstadoCheckoutPersistido.RECONCILIANDO,
                    sesion.id(), sesion.expiraEn(), false, ahora);
        } else if ("expired".equals(sesion.estado())) {
            boolean sinSuscripcionNoTerminal = !stripe.tieneSuscripcionNoTerminal(sesion.customerId());
            repositorio.reconciliarCheckout(intento.intentoId(), EstadoCheckoutPersistido.EXPIRADO,
                    sesion.id(), sesion.expiraEn(), sinSuscripcionNoTerminal, ahora);
        } else {
            throw servicioNoDisponible();
        }
        return sesion;
    }

    private void validarSesion(UUID clienteId, IntentoCheckoutPersistido intento,
            ProveedorStripeMembresia.CheckoutRemoto sesion, String customerEsperado) {
        if (sesion == null || sesion.id() == null || !sesion.id().startsWith("cs_test_")
                || sesion.livemode() || !"subscription".equals(sesion.mode()) || sesion.expiraEn() == null
                || !clienteId.toString().equals(metadata(sesion, CLAVE_METADATA_CLIENTE))
                || !intento.intentoId().toString().equals(metadata(sesion, CLAVE_METADATA_INTENTO))
                || !catalogo.precioId().equals(metadata(sesion, CLAVE_METADATA_PRECIO))
                || customerEsperado == null || !customerEsperado.equals(sesion.customerId())) {
            throw servicioNoDisponible();
        }
        if ("open".equals(sesion.estado())) {
            try {
                if (sesion.url() == null) {
                    throw servicioNoDisponible();
                }
                URI url = URI.create(sesion.url());
                if (!"https".equalsIgnoreCase(url.getScheme())
                        || !"checkout.stripe.com".equalsIgnoreCase(url.getHost())
                        || url.getUserInfo() != null) {
                    throw servicioNoDisponible();
                }
            } catch (IllegalArgumentException excepcion) {
                throw servicioNoDisponible();
            }
        }
    }

    private String estadoActual(UUID clienteId, UUID intentoId) {
        return repositorio.consultarCheckout(clienteId, intentoId)
                .map(IntentoCheckoutPersistido::estado).map(Enum::name).orElse("RECONCILIANDO");
    }

    private RespuestaEstadoCheckoutMembresia respuestaEstado(
            IntentoCheckoutPersistido intento, ProveedorStripeMembresia.CheckoutRemoto sesion) {
        String estado = estadoActual(intento.clienteId(), intento.intentoId());
        return new RespuestaEstadoCheckoutMembresia(intento.intentoId(),
                estado,
                !esTerminal(EstadoCheckoutPersistido.valueOf(estado))
                        && sesion != null && "open".equals(sesion.estado()) ? sesion.url() : null,
                sesion == null ? intento.expiraEn() : sesion.expiraEn());
    }

    private static String metadata(ProveedorStripeMembresia.CheckoutRemoto sesion, String clave) {
        return sesion.metadata() == null ? null : sesion.metadata().get(clave);
    }

    private void exigirStripeDisponible() {
        if (!propiedades.stripeDisponible()) {
            throw servicioNoDisponible();
        }
    }

    private static String validarClave(String valor) {
        if (valor == null || valor.length() < 8 || valor.length() > 255
                || !valor.matches("[A-Za-z0-9._:-]+")) {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST,
                    "La solicitud no incluye una clave válida.", "CLAVE_IDEMPOTENCIA_NO_VALIDA");
        }
        return valor;
    }

    private static IntentoCheckoutPersistido validarReserva(ReservaCheckout reserva) {
        return switch (reserva.resultado()) {
            case NUEVA, REPLAY -> reserva.intento();
            case IDEMPOTENCIA_REUTILIZADA -> throw conflicto("CLAVE_IDEMPOTENCIA_REUTILIZADA",
                    "Esta solicitud ya se procesó con otros datos.");
            case MEMBRESIA_NO_ELEGIBLE -> throw conflicto("MEMBRESIA_NO_ELEGIBLE",
                    "Tu membresía actual no permite iniciar otro pago.");
            case CHECKOUT_PENDIENTE -> throw conflicto("CHECKOUT_PENDIENTE",
                    "Ya hay un pago en curso para esta cuenta.");
            case LIMITE_ALCANZADO -> throw new ErrorConfiguracion(HttpStatus.TOO_MANY_REQUESTS,
                    "Espera un momento antes de volver a intentarlo.", "INTENTOS_LIMITADOS");
        };
    }

    private static boolean esTerminal(EstadoCheckoutPersistido estado) {
        return estado == EstadoCheckoutPersistido.COMPLETADO || estado == EstadoCheckoutPersistido.EXPIRADO
                || estado == EstadoCheckoutPersistido.FALLIDO;
    }

    private static ErrorConfiguracion conflicto(String codigo, String mensaje) {
        return new ErrorConfiguracion(HttpStatus.CONFLICT, mensaje, codigo);
    }

    private static ErrorConfiguracion servicioNoDisponible() {
        return new ErrorConfiguracion(HttpStatus.SERVICE_UNAVAILABLE,
                "No pudimos consultar el pago en este momento. Inténtalo más tarde.", "STRIPE_NO_DISPONIBLE");
    }

    private static String hash(String valor) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(valor.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException("No está disponible SHA-256.", excepcion);
        }
    }

    private static String integrationIdentifier(UUID intentoId) {
        byte[] digest;
        try {
            digest = MessageDigest.getInstance("SHA-256")
                    .digest(intentoId.toString().getBytes(StandardCharsets.UTF_8));
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException("No está disponible SHA-256.", excepcion);
        }
        StringBuilder sufijo = new StringBuilder(8);
        for (int indice = 0; indice < 8; indice++) {
            sufijo.append((char) ('a' + Byte.toUnsignedInt(digest[indice]) % 26));
        }
        return "smartparking-" + sufijo;
    }
}
