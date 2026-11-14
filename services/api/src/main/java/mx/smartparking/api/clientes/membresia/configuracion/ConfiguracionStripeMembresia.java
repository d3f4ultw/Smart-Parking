package mx.smartparking.api.clientes.membresia.configuracion;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/** Prepara la configuración de Stripe que se usa para las operaciones de membresía. */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(StripeMembresiaPropiedades.class)
public class ConfiguracionStripeMembresia {
}
