package mx.smartparking.api.operadores;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.activacion.PreparacionInvitacionOperador;
import mx.smartparking.api.activacion.ServicioActivacionOperador;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.persistencia.RepositorioOperadores;
import mx.smartparking.api.persistencia.RepositorioOperadores.ComprobanteRegistroOperador;
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
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;

@ExtendWith(MockitoExtension.class)
class ServicioOperadoresTest {

    private static final UUID DUENO_ID = UUID.fromString("85a4bff5-eae0-4ba7-b509-24f4071e05fa");
    private static final UUID OPERADOR_ID = UUID.fromString("8c3d3c62-e588-48dc-96ec-6d9d98c70dcb");
    private static final String CLAVE = "c0d0f0de-7641-4c78-b6a6-e26904c271e8";

    @Mock
    private RepositorioOperadores repositorio;

    @Mock
    private ServicioActivacionOperador activacion;

    @Mock
    private ServicioEventosAdministracion publicadorEventos;

    private List<String> eventos;
    private ServicioOperadores servicio;

    @BeforeEach
    void preparar() {
        eventos = new ArrayList<>();
        servicio = new ServicioOperadores(repositorio, activacion, publicadorEventos, administradorTransacciones());
    }

    @Test
    void altaNuevaSeRechazaHastaRegistrarEmpleado() {
        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () -> servicio.registrar(
                new SolicitudRegistroOperador("  Ana  ", " López ", " Del Río ", "  ANA@Example.Test "),
                CLAVE,
                dueno()));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertEquals("EMPLEADO_REQUERIDO", error.codigo());
        assertEquals(List.of("inicio", "rollback"), eventos);
        verify(repositorio, never()).reservarRegistro(any(UUID.class), anyString(), anyString());
        verify(repositorio, never()).crearOperadorPendiente(any(UUID.class), any(DatosRegistroOperador.class));
        verify(activacion, never()).prepararInicial(any(UUID.class), anyString());
        verify(activacion, never()).enviarInicial(any(PreparacionInvitacionOperador.class));
    }

    @Test
    void reciboHistoricoCompletadoSeReproduceSinCrearNiEnviar() {
        configurarReciboHistorico(EstadoCuentaOperador.PENDIENTE, "ENVIADO", solicitud(), CLAVE);
        configurarEstadoActual(EstadoCuentaOperador.PENDIENTE, "ENVIADO");

        RespuestaRegistroOperador respuesta = servicio.registrar(solicitud(), CLAVE, dueno());

        assertEquals(OPERADOR_ID, respuesta.id());
        assertEquals("ENVIADO", respuesta.estadoInvitacion());
        verify(repositorio, never()).reservarRegistro(any(UUID.class), anyString(), anyString());
        verify(repositorio, never()).crearOperadorPendiente(any(UUID.class), any(DatosRegistroOperador.class));
        verify(repositorio).buscarPorId(OPERADOR_ID);
        verify(activacion, never()).enviarInicial(any(PreparacionInvitacionOperador.class));
        verify(publicadorEventos, never()).publicarDirectorioOperadorActualizado();
    }

    @Test
    void repeticionDespuesDeActivarDevuelveEstadoActualSinReenviarInvitacion() {
        configurarReciboHistorico(EstadoCuentaOperador.ACTIVA, "CONSUMIDA", solicitud(), CLAVE);
        configurarEstadoActual(EstadoCuentaOperador.ACTIVA, "CONSUMIDA");

        RespuestaRegistroOperador respuesta = servicio.registrar(solicitud(), CLAVE, dueno());

        assertEquals(new RespuestaRegistroOperador(OPERADOR_ID, EstadoCuentaOperador.ACTIVA, "CONSUMIDA"), respuesta);
        verify(repositorio, never()).crearOperadorPendiente(any(UUID.class), any(DatosRegistroOperador.class));
        verify(repositorio).buscarPorId(OPERADOR_ID);
        verify(activacion, never()).enviarInicial(any(PreparacionInvitacionOperador.class));
        verify(publicadorEventos, never()).publicarDirectorioOperadorActualizado();
    }

    @Test
    void validaLongitudUtf16AntesDeRechazarElAltaNueva() {
        String nombreMaximo = "😀".repeat(60);
        ErrorConfiguracion altaNueva = assertThrows(ErrorConfiguracion.class, () -> servicio.registrar(
                new SolicitudRegistroOperador("  " + nombreMaximo + "  ", "López", null, "ana@example.test"),
                CLAVE, dueno()));
        assertEquals("EMPLEADO_REQUERIDO", altaNueva.codigo());

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () -> servicio.registrar(
                new SolicitudRegistroOperador("😀".repeat(61), "López", null, "ana@example.test"),
                CLAVE, dueno()));
        assertEquals(HttpStatus.BAD_REQUEST, error.estadoHttp());
        assertEquals("SOLICITUD_NO_VALIDA", error.codigo());
    }

    @Test
    void claveHistoricaConHuellaDistintaDevuelveConflicto() {
        configurarReciboHistorico(EstadoCuentaOperador.PENDIENTE, "ENVIADO", solicitud(), CLAVE);

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.registrar(
                        new SolicitudRegistroOperador("Ana", "Apellido distinto", null, "ana@example.test"),
                        CLAVE,
                        dueno()));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertEquals("CLAVE_IDEMPOTENCIA_REUTILIZADA", error.codigo());
        verify(repositorio, never()).reservarRegistro(any(UUID.class), anyString(), anyString());
        verify(repositorio, never()).crearOperadorPendiente(any(UUID.class), any(DatosRegistroOperador.class));
        verify(activacion, never()).enviarInicial(any(PreparacionInvitacionOperador.class));
    }

    @Test
    void altaNuevaNoValidaOrigenNiCreaReservaAntesDeExigirEmpleado() {
        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.registrar(solicitud(), CLAVE, dueno()));

        assertEquals("EMPLEADO_REQUERIDO", error.codigo());
        verify(repositorio, never()).reservarRegistro(any(UUID.class), anyString(), anyString());
        verify(repositorio, never()).crearOperadorPendiente(any(UUID.class), any(DatosRegistroOperador.class));
        verify(activacion, never()).validarOrigenConfigurado();
        verify(activacion, never()).prepararInicial(any(UUID.class), anyString());
        verify(activacion, never()).enviarInicial(any(PreparacionInvitacionOperador.class));
    }

    @Test
    void operadorNoPuedeConsultarElDirectorioDeDueno() {
        PrincipalPropietario operador = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.OPERADOR, 1, 0, "operador@example.test");

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () -> servicio.listar("1", operador));

        assertEquals(HttpStatus.FORBIDDEN, error.estadoHttp());
        verify(repositorio, never()).consultarPagina(anyInt(), anyInt(), any(), any());
    }

    @Test
    void directorioUsaDiezElementosPorPagina() {
        Operador item = new Operador(
                OPERADOR_ID, "Ana", "López", null, "ana@example.test",
                EstadoCuentaOperador.PENDIENTE, "EXPIRADA", true);
        when(repositorio.consultarPagina(3, 10, null, null)).thenReturn(
                new RepositorioOperadores.ResultadoPaginaOperadores(List.of(item), 3, 21, 3));
        when(publicadorEventos.cursorActual()).thenAnswer(invocacion -> {
            eventos.add("cursor");
            return "2d329f2c-e53c-47a9-8f22-76997aa50100:4";
        });

        PaginaOperadores pagina = servicio.listar("3", dueno());

        assertEquals(10, pagina.tamanoPagina());
        assertEquals(21, pagina.totalRegistros());
        assertEquals("EXPIRADA", pagina.items().getFirst().estadoInvitacion());
        assertEquals(true, pagina.items().getFirst().puedeReemitirInvitacion());
        assertEquals("2d329f2c-e53c-47a9-8f22-76997aa50100:4", pagina.cursorEventos());
        assertEquals("cursor", eventos.getFirst());
    }

    @Test
    void directorioNormalizaBusquedaYCombinaEstadoAntesDePaginar() {
        when(repositorio.consultarPagina(2, 10, "Ana Lopez", EstadoCuentaOperador.INACTIVA)).thenReturn(
                new RepositorioOperadores.ResultadoPaginaOperadores(List.of(), 2, 10, 1));

        servicio.listar("2", "  Ana Lopez  ", " inactiva ", dueno());

        verify(repositorio).consultarPagina(2, 10, "Ana Lopez", EstadoCuentaOperador.INACTIVA);
    }

    @Test
    void estadoDeFiltroDesconocidoDevuelveErrorAntesDeConsultarRepositorio() {
        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.listar("1", "Ana", "ACTIVO", dueno()));

        assertEquals(HttpStatus.BAD_REQUEST, error.estadoHttp());
        assertEquals("ESTADO_NO_VALIDO", error.codigo());
        verify(repositorio, never()).consultarPagina(anyInt(), anyInt(), any(), any());
    }

    private void configurarReciboHistorico(
            EstadoCuentaOperador estadoActual, String estadoInvitacion,
            SolicitudRegistroOperador solicitud, String clave) {
        DatosRegistroOperador datos = new DatosRegistroOperador(
                solicitud.nombres(), solicitud.primerApellido(), solicitud.segundoApellido(),
                solicitud.correo().trim().toLowerCase(java.util.Locale.ROOT));
        String huella = huella(datos);
        when(repositorio.buscarComprobante(eq(DUENO_ID), anyString())).thenReturn(
                Optional.of(new ComprobanteRegistroOperador(huella, "COMPLETADA", OPERADOR_ID)));
    }

    private static String huella(DatosRegistroOperador datos) {
        try {
            java.security.MessageDigest digest = java.security.MessageDigest.getInstance("SHA-256");
            agregarCampo(digest, datos.nombres());
            agregarCampo(digest, datos.primerApellido());
            agregarCampo(digest, datos.segundoApellido());
            agregarCampo(digest, datos.correo());
            return java.util.HexFormat.of().formatHex(digest.digest());
        } catch (java.security.NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException(excepcion);
        }
    }

    private static void agregarCampo(java.security.MessageDigest digest, String campo) {
        if (campo == null) {
            digest.update(java.nio.ByteBuffer.allocate(Integer.BYTES).putInt(-1).array());
            return;
        }
        byte[] valor = campo.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        digest.update(java.nio.ByteBuffer.allocate(Integer.BYTES).putInt(valor.length).array());
        digest.update(valor);
    }

    private void configurarEstadoActual(EstadoCuentaOperador estadoActual, String estadoInvitacion) {
        when(repositorio.buscarPorId(OPERADOR_ID)).thenReturn(Optional.of(new Operador(
                OPERADOR_ID, "Ana", "López", null, "ana@example.test",
                estadoActual, estadoInvitacion, false)));
    }

    private static SolicitudRegistroOperador solicitud() {
        return new SolicitudRegistroOperador("Ana", "López", null, "ana@example.test");
    }

    private static PrincipalPropietario dueno() {
        return new PrincipalPropietario(DUENO_ID, RolCuenta.DUENO, 1, 1, "dueno@example.test");
    }

    private PlatformTransactionManager administradorTransacciones() {
        return new PlatformTransactionManager() {
            @Override
            public TransactionStatus getTransaction(TransactionDefinition definicion) {
                eventos.add("inicio");
                return new SimpleTransactionStatus();
            }

            @Override
            public void commit(TransactionStatus estado) {
                eventos.add("commit");
            }

            @Override
            public void rollback(TransactionStatus estado) {
                eventos.add("rollback");
            }
        };
    }
}
