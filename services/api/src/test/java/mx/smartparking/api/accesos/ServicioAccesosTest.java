package mx.smartparking.api.accesos;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Instant;
import java.util.List;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionStatus;

class ServicioAccesosTest {
    private final RepositorioAccesosJdbc repositorio = mock(RepositorioAccesosJdbc.class);
    private final ServicioEventosAdministracion eventos = mock(ServicioEventosAdministracion.class);
    private final PlatformTransactionManager administrador = mock(PlatformTransactionManager.class);

    private ServicioAccesos servicio() {
        when(administrador.getTransaction(any())).thenReturn(mock(TransactionStatus.class));
        when(eventos.cursorActual()).thenReturn("cursor-prueba");
        return new ServicioAccesos(repositorio, eventos, administrador);
    }

    @Test
    void calculaDisponiblesYAcotaElResultadoACero() {
        when(repositorio.consultarCapacidad())
                .thenReturn(new RepositorioAccesosJdbc.Capacidad(5, 3))
                .thenReturn(new RepositorioAccesosJdbc.Capacidad(2, 3));
        ServicioAccesos servicio = servicio();

        var primera = servicio.capacidad();
        assertEquals(5, primera.capacidadTotal());
        assertEquals(3, primera.vehiculosDentro());
        assertEquals(2, primera.capacidadDisponible());
        assertEquals("cursor-prueba", primera.cursorEventos());
        assertEquals(0, servicio.capacidad().capacidadDisponible());
    }

    @Test
    void conservaLaTarjetaCanceladaYLaFechaDeUnaVisitaAbierta() {
        Instant instante = Instant.parse("2026-11-07T23:00:00Z");
        when(repositorio.consultarZonaHoraria()).thenReturn("America/Mexico_City");
        when(repositorio.consultarDentro(1, "")).thenReturn(new RepositorioAccesosJdbc.Pagina(
                List.of(new RepositorioAccesosJdbc.Visita(42, "EMPLEADO", "Persona sintética",
                        "E-0042", "CANCELADA", instante)), 1, false));

        var resultado = servicio().dentro("1", null);
        assertEquals(1, resultado.totalRegistros());
        assertEquals("42", resultado.items().getFirst().movimientoId());
        assertEquals("CANCELADA", resultado.items().getFirst().estadoTarjeta());
        assertEquals("EMPLEADO", resultado.items().getFirst().persona().tipo());
        assertEquals("E-0042", resultado.items().getFirst().persona().codigo());
        assertEquals("2026-11-07T17:00:00-06:00", resultado.items().getFirst().entradaEnLocal());
    }

    @Test
    void paginaInvalidaNoConsultaLasVisitas() {
        ServicioAccesos servicio = servicio();
        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () -> servicio.dentro("0", ""));
        assertEquals(HttpStatus.BAD_REQUEST, error.estadoHttp());
        verify(repositorio, never()).consultarDentro(anyInt(), anyString());
    }

    @Test
    void validaYRecortaLaBusquedaAntesDeConsultar() {
        when(repositorio.consultarZonaHoraria()).thenReturn("America/Mexico_City");
        when(repositorio.consultarDentro(1, "E-0001"))
                .thenReturn(new RepositorioAccesosJdbc.Pagina(List.of(), 0, false));
        ServicioAccesos servicio = servicio();
        servicio.dentro("1", "  E-0001  ");
        verify(repositorio).consultarDentro(1, "E-0001");
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ErrorConfiguracion.class,
                () -> servicio.dentro("1", "x".repeat(101))).estadoHttp());
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ErrorConfiguracion.class,
                () -> servicio.dentro("1", "nombre\n")).estadoHttp());
    }
}

