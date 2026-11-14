package mx.smartparking.api.rfid1.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.EstadoConfiguracion;
import mx.smartparking.api.configuracion.TipoEstacionamiento;
import mx.smartparking.api.eventos.PublicadorTarjetasRfid1;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.CandidatoPersona;
import mx.smartparking.api.rfid1.persistencia.RepositorioTarjetasRfid;
import mx.smartparking.api.rfid1.persistencia.RepositorioTarjetasRfid.CandidatoRfid1Persistido;
import mx.smartparking.api.rfid1.persistencia.RepositorioTarjetasRfid.ResultadoCancelacionTarjetaRfid1;
import mx.smartparking.api.rfid1.persistencia.RepositorioTarjetasRfid.TarjetaRfid1Persistida;
import mx.smartparking.api.persistencia.ConfiguracionPersistida;
import mx.smartparking.api.persistencia.RepositorioConfiguracion;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;

class ServicioTarjetasRfid1Test {

    private static final Instant AHORA = Instant.parse("2026-10-28T14:00:00Z");
    private static final PrincipalPropietario DUENO = new PrincipalPropietario(
            UUID.fromString("d6a191d4-27e4-48a3-82af-4d5e69c9bfbd"), RolCuenta.DUENO, 3, 8, "dueno@test.invalid");

    @Test
    void busquedaSoloMarcaElegiblesPersonasActivasSinTarjetaActiva() {
        RepositorioTarjetasRfid repositorio = mock(RepositorioTarjetasRfid.class);
        AdministradorTransaccionesFalso transacciones = new AdministradorTransaccionesFalso();
        var servicio = servicio(repositorio, transacciones, mock(PublicadorTarjetasRfid1.class));
        when(repositorio.buscarPersonas("EMPLEADO", "ab", 10)).thenReturn(List.of(
                candidato(false), new CandidatoRfid1Persistido(
                        "EMPLEADO", "E-0002", "Otra Persona", "ACTIVO", true),
                new CandidatoRfid1Persistido("EMPLEADO", "E-0003", "Persona Inactiva", "INACTIVO", false)));

        var candidatos = servicio.buscarPersonas("EMPLEADO", "ab", DUENO);

        assertEquals(3, candidatos.size());
        assertTrue(candidatos.getFirst().elegible());
        assertFalse(candidatos.get(1).elegible());
        assertEquals("PERSONA_CON_TARJETA", candidatos.get(1).motivoNoElegible());
        assertFalse(candidatos.getLast().elegible());
        assertEquals("PERSONA_INACTIVA", candidatos.getLast().motivoNoElegible());
        assertEquals(1, transacciones.confirmadas);
    }

    @Test
    void clienteSinMembresiaPermaneceVisiblePeroNoEsElegible() {
        RepositorioTarjetasRfid repositorio = mock(RepositorioTarjetasRfid.class);
        var servicio = servicio(repositorio, new AdministradorTransaccionesFalso(), mock(PublicadorTarjetasRfid1.class));
        when(repositorio.buscarPersonas("CLIENTE", "ab", 10)).thenReturn(List.of(
                new CandidatoRfid1Persistido(
                        "CLIENTE", "CLI-0001", "Cliente sin membresía", "ACTIVA", false, "SIN_MEMBRESIA"),
                new CandidatoRfid1Persistido(
                        "CLIENTE", "CLI-0002", "Cliente con membresía", "ACTIVA", false, "ACTIVA"),
                new CandidatoRfid1Persistido(
                        "CLIENTE", "CLI-0003", "Cliente con pago pendiente", "ACTIVA", false, "PENDIENTE")));

        List<CandidatoPersona> candidatos = servicio.buscarPersonas("CLIENTE", "ab", DUENO);

        assertEquals(3, candidatos.size());
        assertFalse(candidatos.getFirst().elegible());
        assertEquals("CLIENTE_SIN_MEMBRESIA", candidatos.getFirst().motivoNoElegible());
        assertTrue(candidatos.get(1).elegible());
        assertNull(candidatos.get(1).motivoNoElegible());
        assertTrue(candidatos.getLast().elegible());
        assertNull(candidatos.getLast().motivoNoElegible());
    }

    @Test
    void busquedaCortaNoConsultaElDirectorio() {
        RepositorioTarjetasRfid repositorio = mock(RepositorioTarjetasRfid.class);
        var servicio = servicio(repositorio, new AdministradorTransaccionesFalso(), mock(PublicadorTarjetasRfid1.class));

        assertTrue(servicio.buscarPersonas("CLIENTE", "a", DUENO).isEmpty());

        verify(repositorio, never()).buscarPersonas("CLIENTE", "a", 10);
    }

    @Test
    void busquedaMixtaLimitaCandidatosYConservaElTipoReal() {
        RepositorioTarjetasRfid repositorio = mock(RepositorioTarjetasRfid.class);
        var servicio = servicio(repositorio, new AdministradorTransaccionesFalso(), mock(PublicadorTarjetasRfid1.class));
        when(repositorio.buscarPersonas("MIXTO", "ab", 10)).thenReturn(List.of(
                new CandidatoRfid1Persistido("CLIENTE", "CLI-0001", "Cliente Prueba", "ACTIVA", false),
                new CandidatoRfid1Persistido("EMPLEADO", "E-0001", "Empleado Prueba", "ACTIVO", false)));

        var candidatos = servicio.buscarPersonas("MIXTO", "ab", DUENO);

        assertEquals(List.of("CLIENTE", "EMPLEADO"), candidatos.stream()
                .map(candidato -> candidato.tipoEntidad()).toList());
        verify(repositorio).buscarPersonas("MIXTO", "ab", 10);
    }

    @Test
    void modalidadPublicaLimitaBusquedaMixtaASoloClientes() {
        RepositorioTarjetasRfid repositorio = mock(RepositorioTarjetasRfid.class);
        var servicio = servicio(repositorio, new AdministradorTransaccionesFalso(),
                mock(PublicadorTarjetasRfid1.class), TipoEstacionamiento.PUBLICO);
        when(repositorio.buscarPersonas("CLIENTE", "ab", 10)).thenReturn(List.of(
                new CandidatoRfid1Persistido("CLIENTE", "CLI-0001", "Cliente Prueba", "ACTIVA", false)));

        var candidatos = servicio.buscarPersonas("MIXTO", "ab", DUENO);

        assertEquals(List.of("CLIENTE"), candidatos.stream().map(CandidatoPersona::tipoEntidad).toList());
        verify(repositorio).buscarPersonas("CLIENTE", "ab", 10);
        verify(repositorio, never()).buscarPersonas("MIXTO", "ab", 10);
    }

    @Test
    void modalidadDevuelveUnicamenteElTipoDeEstacionamiento() {
        RepositorioTarjetasRfid repositorio = mock(RepositorioTarjetasRfid.class);
        var servicio = servicio(repositorio, new AdministradorTransaccionesFalso(),
                mock(PublicadorTarjetasRfid1.class), TipoEstacionamiento.PRIVADO);

        assertEquals(TipoEstacionamiento.PRIVADO, servicio.consultarModalidad(DUENO).tipoEstacionamiento());
    }

    @Test
    void directorioMixtoPasaElFiltroYConservaLosTiposDeLaPagina() {
        RepositorioTarjetasRfid repositorio = mock(RepositorioTarjetasRfid.class);
        var servicio = servicio(repositorio, new AdministradorTransaccionesFalso(), mock(PublicadorTarjetasRfid1.class));
        when(repositorio.contarTarjetas("MIXTO", "TODAS", "", true)).thenReturn(2L);
        when(repositorio.listarTarjetas("MIXTO", "TODAS", "", 10, 10, true)).thenReturn(List.of(
                tarjeta(), new TarjetaRfid1Persistida(9, "04D5E6F7", "EMPLEADO", "E-0002", "Empleado Prueba",
                        "ACTIVA", AHORA, null)));

        var pagina = servicio.listar("MIXTO", "TODAS", "2", null, DUENO);

        assertEquals(2, pagina.total());
        assertEquals(List.of("CLIENTE", "EMPLEADO"), pagina.items().stream()
                .map(item -> item.tipoEntidad()).toList());
        verify(repositorio).contarTarjetas("MIXTO", "TODAS", "", true);
        verify(repositorio).listarTarjetas("MIXTO", "TODAS", "", 10, 10, true);
    }

    @Test
    void listaTarjetasPaginadaIncluyeUidEnElDtoPrivado() {
        RepositorioTarjetasRfid repositorio = mock(RepositorioTarjetasRfid.class);
        var servicio = servicio(repositorio, new AdministradorTransaccionesFalso(), mock(PublicadorTarjetasRfid1.class));
        when(repositorio.contarTarjetas("CLIENTE", "TODAS", "", true)).thenReturn(11L);
        when(repositorio.listarTarjetas("CLIENTE", "TODAS", "", 10, 10, true)).thenReturn(List.of(tarjeta()));

        var pagina = servicio.listar("CLIENTE", "TODAS", "2", "   ", DUENO);

        assertEquals(2, pagina.pagina());
        assertEquals(11, pagina.total());
        assertEquals(2, pagina.totalPaginas());
        assertEquals(1, pagina.items().size());
        assertEquals("04A1B2C3", pagina.items().getFirst().uid());
    }

    @Test
    void operadorRecibeUidNuloYNoBuscaNiProyectaUidEnListaODetalle() {
        RepositorioTarjetasRfid repositorio = mock(RepositorioTarjetasRfid.class);
        var servicio = servicio(repositorio, new AdministradorTransaccionesFalso(), mock(PublicadorTarjetasRfid1.class));
        PrincipalPropietario operador = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.OPERADOR, 1, 1, "operador@test.invalid");
        when(repositorio.contarTarjetas("MIXTO", "TODAS", "04A1B2C3", false)).thenReturn(1L);
        when(repositorio.listarTarjetas("MIXTO", "TODAS", "04A1B2C3", 0, 10, false))
                .thenReturn(List.of(tarjeta()));
        when(repositorio.buscarTarjeta(8, false)).thenReturn(Optional.of(tarjeta()));

        var pagina = servicio.listar("MIXTO", "TODAS", "1", "04A1B2C3", operador);
        var detalle = servicio.consultar(8, operador);

        assertNull(pagina.items().getFirst().uid());
        assertNull(detalle.uid());
        verify(repositorio).contarTarjetas("MIXTO", "TODAS", "04A1B2C3", false);
        verify(repositorio).listarTarjetas("MIXTO", "TODAS", "04A1B2C3", 0, 10, false);
        verify(repositorio).buscarTarjeta(8, false);
        verify(repositorio, never()).contarTarjetas("MIXTO", "TODAS", "04A1B2C3", true);
        verify(repositorio, never()).buscarTarjeta(8, true);
    }

    @Test
    void directorioUsaLaMismaBusquedaRecortadaEnConteoYPagina() {
        RepositorioTarjetasRfid repositorio = mock(RepositorioTarjetasRfid.class);
        var servicio = servicio(repositorio, new AdministradorTransaccionesFalso(), mock(PublicadorTarjetasRfid1.class));
        when(repositorio.contarTarjetas("EMPLEADO", "ACTIVA", "Ana  Lopez", true)).thenReturn(11L);
        when(repositorio.listarTarjetas("EMPLEADO", "ACTIVA", "Ana  Lopez", 10, 10, true)).thenReturn(List.of());

        var pagina = servicio.listar("EMPLEADO", "ACTIVA", "2", " \u00a0Ana  Lopez\u00a0 ", DUENO);

        assertEquals(11, pagina.total());
        assertEquals(2, pagina.totalPaginas());
        verify(repositorio).contarTarjetas("EMPLEADO", "ACTIVA", "Ana  Lopez", true);
        verify(repositorio).listarTarjetas("EMPLEADO", "ACTIVA", "Ana  Lopez", 10, 10, true);
    }

    @Test
    void directorioRechazaBusquedaLargaOConControlSinConsultarDatos() {
        RepositorioTarjetasRfid repositorio = mock(RepositorioTarjetasRfid.class);
        var servicio = servicio(repositorio, new AdministradorTransaccionesFalso(), mock(PublicadorTarjetasRfid1.class));

        ErrorConfiguracion larga = assertThrows(ErrorConfiguracion.class,
                () -> servicio.listar("MIXTO", "TODAS", "1", "a".repeat(101), DUENO));
        ErrorConfiguracion control = assertThrows(ErrorConfiguracion.class,
                () -> servicio.listar("MIXTO", "TODAS", "1", "abc\u0085", DUENO));

        assertEquals(HttpStatus.BAD_REQUEST, larga.estadoHttp());
        assertEquals(HttpStatus.BAD_REQUEST, control.estadoHttp());
        assertFalse(larga.getMessage().contains("a".repeat(101)));
        verify(repositorio, never()).contarTarjetas("MIXTO", "TODAS", "a".repeat(101), true);
        verify(repositorio, never()).contarTarjetas("MIXTO", "TODAS", "abc\u0085", true);
    }

    @Test
    void cancelacionPublicaSoloLaPrimeraTransicionYDespuesDelCommit() {
        RepositorioTarjetasRfid repositorio = mock(RepositorioTarjetasRfid.class);
        AdministradorTransaccionesFalso transacciones = new AdministradorTransaccionesFalso();
        PublicadorTarjetasRfid1 publicador = mock(PublicadorTarjetasRfid1.class);
        var servicio = servicio(repositorio, transacciones, publicador);
        when(repositorio.cancelarTarjeta(9, AHORA)).thenReturn(
                new ResultadoCancelacionTarjetaRfid1("CANCELADA", null, false),
                new ResultadoCancelacionTarjetaRfid1("CANCELADA", null, true));
        doAnswer(invocacion -> {
            assertEquals(1, transacciones.confirmadas);
            return null;
        }).when(publicador).publicarSiActualizadas(true);

        servicio.cancelar(9, DUENO);
        servicio.cancelar(9, DUENO);

        verify(publicador).publicarSiActualizadas(true);
        verify(publicador).publicarSiActualizadas(false);
        assertEquals(2, transacciones.confirmadas);
    }

    @Test
    void busquedaPermiteOperadorDentroDelModulo() {
        RepositorioTarjetasRfid repositorio = mock(RepositorioTarjetasRfid.class);
        var servicio = servicio(repositorio, new AdministradorTransaccionesFalso(), mock(PublicadorTarjetasRfid1.class));
        PrincipalPropietario operador = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.OPERADOR, 1, 1, "operador@test.invalid");
        when(repositorio.buscarPersonas("CLIENTE", "ab", 10)).thenReturn(List.of(
                new CandidatoRfid1Persistido("CLIENTE", "CLI-0001", "Cliente Prueba", "ACTIVA", false)));

        var candidatos = servicio.buscarPersonas("CLIENTE", "ab", operador);

        assertEquals(1, candidatos.size());
        verify(repositorio).buscarPersonas("CLIENTE", "ab", 10);
    }

    private static ServicioTarjetasRfid1 servicio(
            RepositorioTarjetasRfid repositorio,
            AdministradorTransaccionesFalso transacciones,
            PublicadorTarjetasRfid1 publicador) {
        return servicio(repositorio, transacciones, publicador, TipoEstacionamiento.MIXTO);
    }

    private static ServicioTarjetasRfid1 servicio(
            RepositorioTarjetasRfid repositorio,
            AdministradorTransaccionesFalso transacciones,
            PublicadorTarjetasRfid1 publicador,
            TipoEstacionamiento modalidad) {
        return new ServicioTarjetasRfid1(
                repositorio, configuracion(modalidad), transacciones, publicador, Clock.fixed(AHORA, ZoneOffset.UTC));
    }

    private static RepositorioConfiguracion configuracion(TipoEstacionamiento modalidad) {
        RepositorioConfiguracion repositorio = mock(RepositorioConfiguracion.class);
        ConfiguracionPersistida valor = new ConfiguracionPersistida(
                EstadoConfiguracion.CONFIGURADA, 1, 1, null, null, null, null, null, null, null, null,
                modalidad, null, null, null, null, null, null, null, null, null, null, null, null);
        when(repositorio.obtener()).thenReturn(valor);
        when(repositorio.bloquear()).thenReturn(valor);
        return repositorio;
    }

    private static CandidatoRfid1Persistido candidato(boolean tieneTarjeta) {
        return new CandidatoRfid1Persistido("EMPLEADO", "E-0001", "Persona Prueba", "ACTIVO", tieneTarjeta);
    }

    private static TarjetaRfid1Persistida tarjeta() {
        return new TarjetaRfid1Persistida(8, "04A1B2C3", "CLIENTE", "CLI-0001", "Persona Prueba",
                "ACTIVA", AHORA, null);
    }

    private static final class AdministradorTransaccionesFalso implements PlatformTransactionManager {
        private int confirmadas;

        @Override
        public TransactionStatus getTransaction(TransactionDefinition definicion) {
            return new SimpleTransactionStatus();
        }

        @Override
        public void commit(TransactionStatus estado) {
            confirmadas++;
        }

        @Override
        public void rollback(TransactionStatus estado) {
            throw new AssertionError("No se esperaba rollback en esta prueba.");
        }
    }
}
