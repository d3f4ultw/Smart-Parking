package mx.smartparking.api.activacion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Set;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

class ServicioActivacionOperadorOrigenTest extends ServicioActivacionOperadorTestSupport {

    @Test
    void origenHttpRemotoSeRechazaAntesDePersistir() {
        servicio = new ServicioActivacionOperador(repositorio, notificador, codificador,
                new ProteccionIntentosActivacion(Clock.fixed(AHORA, ZoneOffset.UTC)),
                new AdministradorTransaccionesSimple(), "http://parking.example.test",
                Clock.fixed(AHORA, ZoneOffset.UTC), new java.security.SecureRandom());

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.prepararInicial(OPERADOR_ID, "operador@example.test"));

        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, error.estadoHttp());
        verify(repositorio, never()).crearInicial(any(UUID.class), anyString(), any(Instant.class), any(Instant.class));
    }

    @Test
    void aceptaOrigenHttpDeLoopbackConFlagEnPerfilesLocales() {
        for (String perfil : Set.of("local", "dev", "test")) {
            servicio = servicioConOrigenYPerfiles("http://localhost:3000", Set.of(perfil), true);

            assertEquals("http://localhost:3000", servicio.origenValidado());
        }
    }

    @Test
    void aceptaDireccionesIpv4EIpv6DeLoopbackConFlagEnDesarrollo() {
        servicio = servicioConOrigenYPerfiles("http://127.0.0.1:3000", Set.of("dev"), true);
        assertEquals("http://127.0.0.1:3000", servicio.origenValidado());

        servicio = servicioConOrigenYPerfiles("http://[::1]:3000", Set.of("dev"), true);
        assertEquals("http://[::1]:3000", servicio.origenValidado());
    }

    @Test
    void rechazaOrigenHttpLocalSinFlagExplicitoAntesDePersistir() {
        servicio = servicioConOrigenYPerfiles("http://localhost:3000", Set.of("test"), false);

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, servicio::validarOrigenConfigurado);

        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, error.estadoHttp());
        verify(repositorio, never()).crearInicial(any(UUID.class), anyString(), any(Instant.class), any(Instant.class));
    }

    @Test
    void rechazaOrigenHttpEnProduccionAunqueElFlagEsteActivo() {
        servicio = servicioConOrigenYPerfiles("http://localhost:3000", Set.of("production"), true);

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                servicio::validarOrigenConfigurado);

        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, error.estadoHttp());
        verify(repositorio, never()).crearInicial(any(UUID.class), anyString(), any(Instant.class), any(Instant.class));
    }

    @Test
    void rechazaOrigenHttpNoLoopbackAunqueElFlagEsteActivo() {
        servicio = servicioConOrigenYPerfiles("http://parking.example.test:3000", Set.of("dev"), true);

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                servicio::validarOrigenConfigurado);

        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, error.estadoHttp());
        verify(repositorio, never()).crearInicial(any(UUID.class), anyString(), any(Instant.class), any(Instant.class));
    }

    @Test
    void rechazaOrigenVacioConCredencialesParametrosFragmentoYOtroEsquemaAntesDePersistir() {
        for (String origenInvalido : new String[] {
            "",
            "http://usuario@localhost:3000",
            "http://localhost:3000?modo=prueba",
            "http://localhost:3000#fragmento",
            "ftp://localhost:3000"
        }) {
            servicio = servicioConOrigenYPerfiles(origenInvalido, Set.of("dev"), true);

            ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                    () -> servicio.prepararInicial(OPERADOR_ID, "operador@example.test"), origenInvalido);

            assertEquals(HttpStatus.SERVICE_UNAVAILABLE, error.estadoHttp());
        }

        verify(repositorio, never()).crearInicial(any(UUID.class), anyString(), any(Instant.class), any(Instant.class));
    }

    @Test
    void aceptaOrigenHttpsEnPerfilProduccion() {
        servicio = servicioConOrigenYPerfiles("https://parking.example.test", Set.of("production"), false);

        servicio.prepararInicial(OPERADOR_ID, "operador@example.test");

        verify(repositorio).crearInicial(eq(OPERADOR_ID), anyString(), eq(AHORA), eq(AHORA.plusSeconds(7200)));
    }
}
