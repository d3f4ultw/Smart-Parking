package mx.smartparking.api.rfid2.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.time.LocalTime;
import java.time.ZoneId;
import java.time.Clock;
import java.util.Optional;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Predicate;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.EstadoConfiguracion;
import mx.smartparking.api.configuracion.ModoHorario;
import mx.smartparking.api.persistencia.ConfiguracionPersistida;
import mx.smartparking.api.persistencia.RepositorioConfiguracion;
import mx.smartparking.api.rfid2.persistencia.RepositorioRfid2;
import mx.smartparking.api.rfid2.persistencia.ResultadoEntradaRfid2;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.HttpStatus;

class ServicioRfid2Test {

    @Test
    void rechazaUidInvalidoAntesDeConsultarPersistencia() {
        RepositorioRfid2 repositorio = mock(RepositorioRfid2.class);
        RepositorioConfiguracion configuracion = mock(RepositorioConfiguracion.class);
        ServicioRfid2 servicio = new ServicioRfid2(repositorio, configuracion);

        ErrorConfiguracion error = assertThrows(
                ErrorConfiguracion.class, () -> servicio.registrarEntrada("NO-ES-UID", "550e8400-e29b-41d4-a716-446655440000"));

        assertEquals(HttpStatus.BAD_REQUEST, error.estadoHttp());
        assertEquals("LECTURA_NO_VALIDA", error.codigo());
        verifyNoInteractions(repositorio, configuracion);
    }

    @Test
    void intervaloDiarioIncluyeAperturaYExcluyeCierre() {
        Predicate<LocalTime> horario = horario(ModoHorario.INTERVALO_DIARIO,
                LocalTime.of(8, 0), LocalTime.of(18, 0));

        assertFalse(horario.test(LocalTime.of(7, 59, 59)));
        assertTrue(horario.test(LocalTime.of(8, 0)));
        assertTrue(horario.test(LocalTime.of(17, 59, 59)));
        assertFalse(horario.test(LocalTime.of(18, 0)));
    }

    @Test
    void intervaloNocturnoCruzaMedianoche() {
        Predicate<LocalTime> horario = horario(ModoHorario.INTERVALO_DIARIO,
                LocalTime.of(22, 0), LocalTime.of(6, 0));

        assertFalse(horario.test(LocalTime.of(21, 59, 59)));
        assertTrue(horario.test(LocalTime.of(22, 0)));
        assertTrue(horario.test(LocalTime.MIDNIGHT));
        assertTrue(horario.test(LocalTime.of(5, 59, 59)));
        assertFalse(horario.test(LocalTime.of(6, 0)));
    }

    @Test
    void continuoPermiteCualquierHora() {
        Predicate<LocalTime> horario = horario(ModoHorario.CONTINUO_24_7, null, null);

        assertTrue(horario.test(LocalTime.MIDNIGHT));
        assertTrue(horario.test(LocalTime.of(12, 0)));
        assertTrue(horario.test(LocalTime.MAX));
    }

    @Test
    void configuracionLentaAgotaElPlazoAntesDeIniciarElRepositorio() {
        RepositorioRfid2 repositorio = mock(RepositorioRfid2.class);
        RepositorioConfiguracion configuracion = mock(RepositorioConfiguracion.class);
        AtomicLong nanos = new AtomicLong();
        when(configuracion.buscar()).thenAnswer(invocacion -> {
            nanos.addAndGet(TimeUnit.SECONDS.toNanos(3));
            return Optional.empty();
        });
        ServicioRfid2 servicio = new ServicioRfid2(repositorio, configuracion, Clock.systemUTC(), nanos::get);
        assertThrows(DataAccessResourceFailureException.class, () -> servicio.registrarEntrada(
                "12345678", "550e8400-e29b-41d4-a716-446655440000"));
        verifyNoInteractions(repositorio);
    }

    private static Predicate<LocalTime> horario(ModoHorario modo, LocalTime apertura, LocalTime cierre) {
        RepositorioRfid2 repositorio = mock(RepositorioRfid2.class);
        RepositorioConfiguracion configuracion = mock(RepositorioConfiguracion.class);
        ConfiguracionPersistida actual = new ConfiguracionPersistida(
                EstadoConfiguracion.CONFIGURADA, 1, 1, null, null, null, null, null, null, null,
                null, null, modo, "America/Mexico_City", apertura, cierre,
                null, null, null, null, null, null, null, null);
        when(configuracion.buscar()).thenReturn(Optional.of(actual));
        AtomicReference<Predicate<LocalTime>> condicion = new AtomicReference<>();
        when(repositorio.registrarEntrada(anyString(), any(), any(), any(), any(), anyLong(), any())).thenAnswer(invocacion -> {
            assertEquals(ZoneId.of("America/Mexico_City"), invocacion.getArgument(3));
            condicion.set(invocacion.getArgument(4));
            return ResultadoEntradaRfid2.autorizada();
        });
        new ServicioRfid2(repositorio, configuracion)
                .registrarEntrada("12345678", "550e8400-e29b-41d4-a716-446655440000");
        return condicion.get();
    }
}
