package mx.smartparking.api;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/** Arranca el servidor que recibe las solicitudes de Smart Parking. */
@SpringBootApplication
public class AplicacionApi {

    /** Pone en marcha el servidor y prepara lo necesario para atender solicitudes. */
    public static void main(String[] argumentos) {
        SpringApplication.run(AplicacionApi.class, argumentos);
    }
}
