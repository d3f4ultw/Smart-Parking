package mx.smartparking.api.clientes.configuracion;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/** Prepara el plan de membresía configurado para que el servidor pueda mostrarlo al cliente. */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(CatalogoMembresia.class)
public class ConfiguracionClientes {
}
