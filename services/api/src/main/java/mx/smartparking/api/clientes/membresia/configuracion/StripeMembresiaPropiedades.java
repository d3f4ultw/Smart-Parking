package mx.smartparking.api.clientes.membresia.configuracion;

import java.net.URI;
import org.springframework.boot.context.properties.ConfigurationProperties;

/** Reúne los datos privados que necesita la conexión de prueba de Stripe para las membresías. */
@ConfigurationProperties(prefix = "smartparking.clientes.membresia.stripe")
public record StripeMembresiaPropiedades(
        String apiKey,
        String webhookSecret,
        String webBaseUrl,
        String apiVersion) {

    private static final String API_VERSION_ACTUAL = "2026-08-26.dahlia";

    public StripeMembresiaPropiedades {
        apiKey = apiKey == null ? "" : apiKey.strip();
        webhookSecret = webhookSecret == null ? "" : webhookSecret.strip();
        webBaseUrl = normalizarOrigen(webBaseUrl);
        apiVersion = apiVersion == null ? "" : apiVersion.strip();
        if (!API_VERSION_ACTUAL.equals(apiVersion)) {
            throw new IllegalArgumentException("La versión de Stripe configurada no está autorizada.");
        }
        if (!apiKey.isEmpty() && !esClaveDePrueba(apiKey)) {
            throw new IllegalArgumentException("La API solo admite credenciales Stripe de prueba.");
        }
    }

    public boolean stripeDisponible() {
        return !apiKey.isEmpty();
    }

    public boolean webhookDisponible() {
        return !webhookSecret.isEmpty();
    }

    private static boolean esClaveDePrueba(String clave) {
        return clave.startsWith("sk_test_") || clave.startsWith("rk_test_");
    }

    private static String normalizarOrigen(String origen) {
        String valor = origen == null || origen.isBlank()
                ? "http://localhost:3000"
                : origen.strip();
        URI uri = URI.create(valor).normalize();
        String esquema = uri.getScheme();
        String host = uri.getHost();
        boolean origenLocalHttp = "http".equalsIgnoreCase(esquema)
                && ("localhost".equalsIgnoreCase(host)
                        || "127.0.0.1".equals(host)
                        || "::1".equals(host));
        boolean origenHttps = "https".equalsIgnoreCase(esquema) && host != null;
        if ((!origenLocalHttp && !origenHttps)
                || uri.getUserInfo() != null
                || uri.getQuery() != null
                || uri.getFragment() != null
                || uri.getPath() != null && !uri.getPath().isEmpty() && !"/".equals(uri.getPath())) {
            throw new IllegalArgumentException("El origen de retorno debe ser local HTTP o HTTPS válido.");
        }
        return esquema.toLowerCase(java.util.Locale.ROOT) + "://" + uri.getRawAuthority();
    }
}
