package mx.smartparking.api.empleados;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.HexFormat;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.persistencia.RepositorioEmpleados;
import mx.smartparking.api.persistencia.RepositorioEmpleados.ComprobanteRegistroEmpleado;
import mx.smartparking.api.persistencia.RepositorioEmpleados.ResultadoPaginaEmpleados;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;

class ServicioEmpleadosTest {

    private static final String CLAVE = "4c538ee3-079d-40b4-a1bb-43b9e0a42a6e";
    private static final UUID CUENTA = UUID.fromString("db21b3c9-a2b3-4b96-9d27-8d42f03fac76");
    private RepositorioEmpleados repositorio;
    private ServicioEventosAdministracion eventos;
    private ServicioEmpleados servicio;
    private List<String> ordenTransaccional;

    @BeforeEach
    void preparar() {
        repositorio = mock(RepositorioEmpleados.class);
        eventos = mock(ServicioEventosAdministracion.class);
        ordenTransaccional = new ArrayList<>();
        servicio = new ServicioEmpleados(repositorio, eventos, administradorTransacciones());
        doAnswer(invocacion -> {
            ordenTransaccional.add("evento");
            return null;
        }).when(eventos).publicarDirectorioActualizado();
    }

    @Test
    void registraDatosNormalizadosYPublicaSoloDespuesDelCommit() {
        when(repositorio.reservarRegistro(eq(CUENTA), anyString(), anyString())).thenReturn(true);
        when(repositorio.crearEmpleado("Ana", "López", null, null, null)).thenReturn(42L);

        RespuestaRegistroEmpleado respuesta = servicio.registrar(
                new SolicitudRegistroEmpleado("  Ana  ", " López ", "   "), CLAVE, propietario());

        assertEquals(new RespuestaRegistroEmpleado(42L, "E-0042"), respuesta);
        assertEquals("42", respuesta.idTexto());
        verify(repositorio).completarRegistro(eq(CUENTA), anyString(), eq(42L));
        ArgumentCaptor<String> claveHash = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> huella = ArgumentCaptor.forClass(String.class);
        verify(repositorio).reservarRegistro(eq(CUENTA), claveHash.capture(), huella.capture());
        assertEquals(64, claveHash.getValue().length());
        assertNotEquals(CLAVE, claveHash.getValue());
        assertEquals(huellaV4("Ana", "López", null), huella.getValue());
        assertEquals(List.of("inicio", "commit", "evento"), ordenTransaccional);
    }

    @Test
    void listaElegiblesConFiltroDeNombreOCodigoYRevisionVigente() {
        Empleado disponible = empleado(42, EstadoEmpleado.ACTIVO, 7);
        when(eventos.cursorActual()).thenReturn("epoch-1:8");
        when(repositorio.consultarElegiblesParaOperador(2, 10, "E-0042"))
                .thenReturn(new ResultadoPaginaEmpleados(List.of(disponible), 2, 11, 2));

        PaginaEmpleados resultado = servicio.listar("2", " E-0042 ", true);

        assertEquals(List.of(disponible), resultado.items());
        assertEquals("epoch-1:8", resultado.cursorEventos());
        verify(repositorio).consultarElegiblesParaOperador(2, 10, "E-0042");
        verify(repositorio, never()).consultarPagina(2, 10);
    }


    @Test
    void correoOpcionalSeNormalizaYSeGuardaSinCrearCuenta() {
        when(repositorio.reservarRegistro(eq(CUENTA), anyString(), anyString())).thenReturn(true);
        when(repositorio.crearEmpleado("Ana", "López", null, "Ana@Example.invalid", "ana@example.invalid"))
                .thenReturn(43L);

        RespuestaRegistroEmpleado respuesta = servicio.registrar(
                new SolicitudRegistroEmpleado("Ana", "López", null, "  Ana@Example.invalid  "), CLAVE, propietario());

        assertEquals("43", respuesta.idTexto());
        verify(repositorio).crearEmpleado("Ana", "López", null, "Ana@Example.invalid", "ana@example.invalid");
        verify(eventos).publicarDirectorioActualizado();
    }

    @Test
    void correoPresenteUsaUnaHuellaVersionadaDistintaDeLaCompatibilidadV4() {
        ArgumentCaptor<String> huella = ArgumentCaptor.forClass(String.class);
        when(repositorio.reservarRegistro(eq(CUENTA), anyString(), huella.capture())).thenReturn(true);
        when(repositorio.crearEmpleado("Ana", "López", null, "Ana@Example.invalid", "ana@example.invalid"))
                .thenReturn(44L);

        servicio.registrar(
                new SolicitudRegistroEmpleado("Ana", "López", null, "Ana@Example.invalid"), CLAVE, propietario());

        assertNotEquals(huellaV4("Ana", "López", null), huella.getValue());
    }

    @Test
    void repetirClaveConLaMismaHuellaDevuelveElReciboSinCrearNiPublicar() {
        AtomicReference<String> huella = new AtomicReference<>();
        AtomicInteger intentos = new AtomicInteger();
        when(repositorio.reservarRegistro(eq(CUENTA), anyString(), anyString())).thenAnswer(invocacion -> {
            huella.set(invocacion.getArgument(2));
            return intentos.incrementAndGet() == 1;
        });
        when(repositorio.crearEmpleado("Ana", "López", null, null, null)).thenReturn(9L);
        when(repositorio.buscarComprobante(eq(CUENTA), anyString())).thenAnswer(invocacion ->
                Optional.of(new ComprobanteRegistroEmpleado(huella.get(), "COMPLETADA", 9L)));

        RespuestaRegistroEmpleado primera = servicio.registrar(
                new SolicitudRegistroEmpleado(" Ana ", "López", null), CLAVE, propietario());
        RespuestaRegistroEmpleado segunda = servicio.registrar(
                new SolicitudRegistroEmpleado("Ana", "López", " "), CLAVE, propietario());

        assertEquals(primera, segunda);
        verify(repositorio).crearEmpleado("Ana", "López", null, null, null);
        verify(eventos).publicarDirectorioActualizado();
    }

    @Test
    void rechazaLaReutilizacionDeClaveConOtrosDatos() {
        when(repositorio.reservarRegistro(eq(CUENTA), anyString(), anyString())).thenReturn(false);
        when(repositorio.buscarComprobante(eq(CUENTA), anyString())).thenReturn(
                Optional.of(new ComprobanteRegistroEmpleado("0".repeat(64), "COMPLETADA", 9L)));

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () -> servicio.registrar(
                new SolicitudRegistroEmpleado("Ana", "López", null), CLAVE, propietario()));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertEquals("CLAVE_IDEMPOTENCIA_REUTILIZADA", error.codigo());
        verify(repositorio, never()).crearEmpleado(anyString(), anyString(), any(), any(), any());
        verify(eventos, never()).publicarDirectorioActualizado();
    }

    @Test
    void falloAlCompletarReciboRevierteLaTransaccionYSuprimeElEvento() {
        when(repositorio.reservarRegistro(eq(CUENTA), anyString(), anyString())).thenReturn(true);
        when(repositorio.crearEmpleado("Ana", "López", null, null, null)).thenReturn(10L);
        doThrow(new IllegalStateException("fallo simulado"))
                .when(repositorio).completarRegistro(eq(CUENTA), anyString(), eq(10L));

        assertThrows(IllegalStateException.class, () -> servicio.registrar(
                new SolicitudRegistroEmpleado("Ana", "López", null), CLAVE, propietario()));

        assertEquals(List.of("inicio", "rollback"), ordenTransaccional);
        verify(eventos, never()).publicarDirectorioActualizado();
    }

    @Test
    void validaCienPuntosDeCodigoYRechazaCientoUno() {
        when(repositorio.reservarRegistro(eq(CUENTA), anyString(), anyString())).thenReturn(true);
        when(repositorio.crearEmpleado("🙂".repeat(100), "López", null, null, null)).thenReturn(1L);

        servicio.registrar(new SolicitudRegistroEmpleado("🙂".repeat(100), "López", ""), CLAVE, propietario());

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () -> servicio.registrar(
                new SolicitudRegistroEmpleado("🙂".repeat(101), "López", null), CLAVE, propietario()));
        assertEquals("SOLICITUD_NO_VALIDA", error.codigo());
    }

    @Test
    void cursorSeCapturaAntesDeConsultarLaPagina() {
        when(eventos.cursorActual()).thenReturn("epoch-1:4");
        when(repositorio.consultarPagina(3, 10)).thenReturn(new ResultadoPaginaEmpleados(List.of(), 1, 0, 0));

        PaginaEmpleados pagina = servicio.listar("3");

        assertEquals("epoch-1:4", pagina.cursorEventos());
        assertEquals(1, pagina.pagina());
        InOrder orden = inOrder(eventos, repositorio);
        orden.verify(eventos).cursorActual();
        orden.verify(repositorio).consultarPagina(3, 10);
    }

    @Test
    void paginaInvalidaNoLeeElCursorNiLaBase() {
        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () -> servicio.listar("0"));

        assertEquals("PAGINA_NO_VALIDA", error.codigo());
        verify(eventos, never()).cursorActual();
        verify(repositorio, never()).consultarPagina(0, 10);
    }

    @Test
    void contratoDeRegistroYDirectorioUsaPrimerYSegundoApellido() {
        assertEquals(List.of("nombres", "primerApellido", "segundoApellido", "correo"), Arrays.stream(
                SolicitudRegistroEmpleado.class.getRecordComponents()).map(java.lang.reflect.RecordComponent::getName).toList());
        assertEquals(List.of("id", "codigo", "nombres", "primerApellido", "segundoApellido", "estado", "revision",
                        "idTexto", "revisionTexto", "correo", "operador"),
                Arrays.stream(Empleado.class.getRecordComponents()).map(java.lang.reflect.RecordComponent::getName).toList());
    }

    @Test
    void unNoOpNoIncrementaNiPublicaYUnaRevisionObsoletaFallaPrimero() {
        Empleado actual = empleado(7, EstadoEmpleado.ACTIVO, 5);
        when(repositorio.bloquearPorId(7)).thenReturn(Optional.of(actual));

        Empleado sinCambio = servicio.cambiarEstado("7", "ACTIVO", "\"5\"");
        ErrorConfiguracion obsoleta = assertThrows(ErrorConfiguracion.class,
                () -> servicio.cambiarEstado("7", "ACTIVO", "\"4\""));

        assertEquals(actual, sinCambio);
        assertEquals("REVISION_OBSOLETA", obsoleta.codigo());
        verify(repositorio, never()).actualizarEstado(eq(7L), eq(EstadoEmpleado.ACTIVO), eq(6L));
        verify(eventos, never()).publicarDirectorioActualizado();
    }

    @Test
    void transicionDeEstadoIncrementaLaRevisionYPublicaTrasElCommit() {
        Empleado actualizado = empleado(7, EstadoEmpleado.INACTIVO, 6);
        when(repositorio.bloquearPorId(7)).thenReturn(Optional.of(empleado(7, EstadoEmpleado.ACTIVO, 5)));
        when(repositorio.actualizarEstado(7, EstadoEmpleado.INACTIVO, 6)).thenReturn(actualizado);

        Empleado respuesta = servicio.cambiarEstado("7", "INACTIVO", "\"5\"");

        assertEquals(actualizado, respuesta);
        assertEquals(List.of("inicio", "commit", "evento"), ordenTransaccional);
    }


    private static String huellaV4(String... campos) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            for (String campo : campos) {
                if (campo == null) {
                    digest.update(ByteBuffer.allocate(Integer.BYTES).putInt(-1).array());
                } else {
                    byte[] bytes = campo.getBytes(StandardCharsets.UTF_8);
                    digest.update(ByteBuffer.allocate(Integer.BYTES).putInt(bytes.length).array());
                    digest.update(bytes);
                }
            }
            return HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException(excepcion);
        }
    }

    private PrincipalPropietario propietario() {
        return new PrincipalPropietario(CUENTA, mx.smartparking.api.seguridad.RolCuenta.DUENO, 1, 1, "dueno@test.invalid");
    }

    private static Empleado empleado(long id, EstadoEmpleado estado, long revision) {
        return new Empleado(id, Empleado.codigoDe(id), "Ana", "López", null, estado, revision);
    }

    private PlatformTransactionManager administradorTransacciones() {
        return new PlatformTransactionManager() {
            @Override
            public TransactionStatus getTransaction(TransactionDefinition definicion) {
                ordenTransaccional.add("inicio");
                return new SimpleTransactionStatus();
            }

            @Override
            public void commit(TransactionStatus status) {
                ordenTransaccional.add("commit");
            }

            @Override
            public void rollback(TransactionStatus status) {
                ordenTransaccional.add("rollback");
            }
        };
    }
}
