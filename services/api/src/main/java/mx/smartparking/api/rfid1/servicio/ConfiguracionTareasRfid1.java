package mx.smartparking.api.rfid1.servicio;

import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;

/** Programa la limpieza periódica de lecturas de tarjetas que solo se conservan por un tiempo. */
@Configuration
@EnableScheduling
public class ConfiguracionTareasRfid1 {
}
