package mx.smartparking.api.clientes.administracion.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.nullable;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.clientes.administracion.modelo.DetalleClienteAdministracion;
import mx.smartparking.api.clientes.administracion.modelo.PaginaClientesAdministracion;
import mx.smartparking.api.clientes.administracion.persistencia.ClienteFilaPersistido;
import mx.smartparking.api.clientes.administracion.persistencia.DetalleClientePersistido;
import mx.smartparking.api.clientes.administracion.persistencia.RepositorioClientesAdministracion;
import mx.smartparking.api.clientes.administracion.persistencia.ResultadoPaginaClientes;
import mx.smartparking.api.clientes.configuracion.CatalogoMembresia;
import mx.smartparking.api.clientes.modelo.EstadoMembresia;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.SimpleTransactionStatus;

@ExtendWith(MockitoExtension.class)
class ServicioAdministracionClientesTest {

    private static final UUID DUENO_ID = UUID.fromString("8d6e3d1a-7b5c-49f4-a40c-a51a4f66f861");
    private static final PrincipalPropietario DUENO = new PrincipalPropietario(
            DUENO_ID, RolCuenta.DUENO, 1, 1, "dueno@example.test");
    private static final CatalogoMembresia CATALOGO = new CatalogoMembresia(
            "prod_VTMowkF8XuDWIR", "price_1USQ5HAqtHmR2qmyAWwUp5vy",
            "Smart Parking - Membresía Mensual", 39_900, "MXN", "month", 1);

    @Mock
    private RepositorioClientesAdministracion repositorio;

    @Mock
    private ServicioEventosAdministracion eventos;

    @Mock
    private PlatformTransactionManager administradorTransacciones;

    private ServicioAdministracionClientes servicio;

    @BeforeEach
    void preparar() {
        lenient().when(administradorTransacciones.getTransaction(any(TransactionDefinition.class)))
                .thenReturn(new SimpleTransactionStatus());
        lenient().doNothing().when(administradorTransacciones).commit(any());
        lenient().doNothing().when(administradorTransacciones).rollback(any());
        servicio = new ServicioAdministracionClientes(repositorio, eventos, CATALOGO, administradorTransacciones);
    }

    @Test
    void listaDiezElementosNormalizaNombreYConservaCursorYTotales() {
        when(eventos.cursorActual()).thenReturn("00000000-0000-0000-0000-000000000001:7");
        when(repositorio.consultarPagina(2, 10, "activa", null)).thenReturn(new ResultadoPaginaClientes(
                List.of(new ClienteFilaPersistido("CLI-1024", " Ana María ", " López ", "  ", "ACTIVA")),
                2, 14, 14, 2));

        PaginaClientesAdministracion pagina = servicio.listar("2", "activa", DUENO);

        assertEquals(10, pagina.tamanoPagina());
        assertEquals(2, pagina.pagina());
        assertEquals(14, pagina.totalClientes());
        assertEquals(14, pagina.totalRegistros());
        assertEquals(2, pagina.totalPaginas());
        assertEquals("00000000-0000-0000-0000-000000000001:7", pagina.cursorEventos());
        assertEquals("Ana María López", pagina.items().getFirst().nombreCompleto());
        assertEquals(EstadoMembresia.ACTIVA, pagina.items().getFirst().estadoMembresia());
        verify(repositorio).consultarPagina(2, 10, "activa", null);
    }

    @Test
    void traducePaginaFueraDeRangoAlValorEfectivoDelRepositorio() {
        when(eventos.cursorActual()).thenReturn("cursor");
        when(repositorio.consultarPagina(99, 10, "todos", null))
                .thenReturn(new ResultadoPaginaClientes(List.of(), 8, 73, 73, 8));

        PaginaClientesAdministracion pagina = servicio.listar("99", null, DUENO);

        assertEquals(8, pagina.pagina());
        assertEquals(8, pagina.totalPaginas());
        verify(repositorio).consultarPagina(99, 10, "todos", null);
    }

    @Test
    void busquedaCombinaFiltroYNormalizaEspacios() {
        when(eventos.cursorActual()).thenReturn("cursor");
        when(repositorio.consultarPagina(1, 10, "activa", "Ana María"))
                .thenReturn(new ResultadoPaginaClientes(List.of(), 1, 7, 1, 1));

        servicio.listar("1", "activa", "  Ana   María  ", DUENO);

        verify(repositorio).consultarPagina(1, 10, "activa", "Ana María");
    }

    @Test
    void busquedaDemasiadoLargaSeRechazaAntesDeConsultarDatos() {
        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.listar("1", "todos", "a".repeat(101), DUENO));

        assertEquals(HttpStatus.BAD_REQUEST, error.estadoHttp());
        assertEquals("BUSQUEDA_CLIENTE_NO_VALIDA", error.codigo());
        verify(repositorio, never()).consultarPagina(
                anyInt(), anyInt(), nullable(String.class), nullable(String.class));
    }

    @Test
    void paginaMalFormadaDevuelveBadRequestAntesDeConsultarDatos() {
        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.listar("1x", null, DUENO));

        assertEquals(HttpStatus.BAD_REQUEST, error.estadoHttp());
        assertEquals("PAGINA_NO_VALIDA", error.codigo());
        verify(repositorio, never()).consultarPagina(
                anyInt(), anyInt(), nullable(String.class), nullable(String.class));
    }

    @Test
    void filtroEnMayusculasNoSeAceptaComoFiltroHttp() {
        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.listar("1", "ACTIVA", DUENO));

        assertEquals(HttpStatus.BAD_REQUEST, error.estadoHttp());
        assertEquals("FILTRO_MEMBRESIA_NO_VALIDO", error.codigo());
        verify(repositorio, never()).consultarPagina(
                anyInt(), anyInt(), nullable(String.class), nullable(String.class));
    }

    @Test
    void duenoYOperadorPuedenConsultarListaYDetalle() {
        PrincipalPropietario operador = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.OPERADOR, 1, 1, "operador@example.test");
        when(eventos.cursorActual()).thenReturn("cursor");
        when(repositorio.consultarPagina(1, 10, "todos", null)).thenReturn(new ResultadoPaginaClientes(
                List.of(new ClienteFilaPersistido("CLI-1024", "Ana", "López", null, "SIN_MEMBRESIA")),
                1, 1, 1, 1));
        when(repositorio.consultarDetalle("CLI-1024")).thenReturn(Optional.of(
                new DetalleClientePersistido(
                        "CLI-1024", "Ana", "López", null, "SIN_MEMBRESIA",
                        null, null, null, false)));

        for (PrincipalPropietario principal : List.of(DUENO, operador)) {
            PaginaClientesAdministracion pagina = servicio.listar("1", null, principal);
            DetalleClienteAdministracion detalle = servicio.consultarDetalle("CLI-1024", principal);

            assertEquals(1, pagina.totalClientes());
            assertEquals("Ana López", detalle.nombreCompleto());
            assertEquals(EstadoMembresia.SIN_MEMBRESIA, detalle.estadoMembresia());
        }

        verify(repositorio, org.mockito.Mockito.times(2)).consultarPagina(1, 10, "todos", null);
        verify(repositorio, org.mockito.Mockito.times(2)).consultarDetalle("CLI-1024");
    }

    @Test
    void rechazaRolClienteAntesDeConsultarListaODetalle() {
        PrincipalPropietario cliente = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.CLIENTE, 1, 1, "cliente@example.test");

        ErrorConfiguracion errorLista = assertThrows(ErrorConfiguracion.class,
                () -> servicio.listar("1", null, cliente));
        ErrorConfiguracion errorDetalle = assertThrows(ErrorConfiguracion.class,
                () -> servicio.consultarDetalle("CLI-1024", cliente));

        assertEquals(HttpStatus.FORBIDDEN, errorLista.estadoHttp());
        assertEquals(HttpStatus.FORBIDDEN, errorDetalle.estadoHttp());
        verify(repositorio, never()).consultarPagina(
                anyInt(), anyInt(), nullable(String.class), nullable(String.class));
        verify(repositorio, never()).consultarDetalle(any());
    }

    @Test
    void rechazaPrincipalAusenteAntesDeConsultarListaODetalle() {
        ErrorConfiguracion errorLista = assertThrows(ErrorConfiguracion.class,
                () -> servicio.listar("1", null, null));
        ErrorConfiguracion errorDetalle = assertThrows(ErrorConfiguracion.class,
                () -> servicio.consultarDetalle("CLI-1024", null));

        assertEquals(HttpStatus.UNAUTHORIZED, errorLista.estadoHttp());
        assertEquals("SESION_NO_VALIDA", errorLista.codigo());
        assertEquals(HttpStatus.UNAUTHORIZED, errorDetalle.estadoHttp());
        verify(repositorio, never()).consultarPagina(
                anyInt(), anyInt(), nullable(String.class), nullable(String.class));
        verify(repositorio, never()).consultarDetalle(any());
    }

    @Test
    void detalleSinMembresiaMantieneMembresiaNula() {
        when(repositorio.consultarDetalle("CLI-1024")).thenReturn(Optional.of(
                new DetalleClientePersistido(
                        "CLI-1024", "Ana", "López", null, "SIN_MEMBRESIA",
                        null, null, null, false)));

        DetalleClienteAdministracion detalle = servicio.consultarDetalle("CLI-1024", DUENO);

        assertEquals("Ana López", detalle.nombreCompleto());
        assertEquals(EstadoMembresia.SIN_MEMBRESIA, detalle.estadoMembresia());
        assertNull(detalle.membresia());
    }

    @Test
    void detalleActivoIncluyePlanPublicoYFechasAutoritativas() {
        Instant inicio = Instant.parse("2026-10-01T00:00:00Z");
        Instant fin = Instant.parse("2026-11-01T00:00:00Z");
        when(repositorio.consultarDetalle("CLI-1024")).thenReturn(Optional.of(
                new DetalleClientePersistido(
                        "CLI-1024", "Ana", "López", null, "ACTIVA", inicio, fin, fin, false)));

        DetalleClienteAdministracion detalle = servicio.consultarDetalle("CLI-1024", DUENO);

        assertEquals(EstadoMembresia.ACTIVA, detalle.estadoMembresia());
        assertEquals("Smart Parking - Membresía Mensual", detalle.membresia().plan().nombre());
        assertEquals(39_900, detalle.membresia().plan().importeMenorUnidad());
        assertEquals("MXN", detalle.membresia().plan().moneda());
        assertEquals("month", detalle.membresia().plan().intervalo());
        assertEquals(1, detalle.membresia().plan().intervaloCantidad());
        assertEquals(inicio, detalle.membresia().periodoInicio());
        assertEquals(fin, detalle.membresia().siguienteCobroEn());
    }

    @Test
    void validaCodigoYDevuelveNotFoundParaCodigoPublicoDesconocido() {
        ErrorConfiguracion formato = assertThrows(ErrorConfiguracion.class,
                () -> servicio.consultarDetalle("cli-1024", DUENO));
        when(repositorio.consultarDetalle("CLI-9999")).thenReturn(Optional.empty());

        ErrorConfiguracion inexistente = assertThrows(ErrorConfiguracion.class,
                () -> servicio.consultarDetalle("CLI-9999", DUENO));

        assertEquals(HttpStatus.BAD_REQUEST, formato.estadoHttp());
        assertEquals(HttpStatus.NOT_FOUND, inexistente.estadoHttp());
        assertEquals("CLIENTE_NO_ENCONTRADO", inexistente.codigo());
    }
}
