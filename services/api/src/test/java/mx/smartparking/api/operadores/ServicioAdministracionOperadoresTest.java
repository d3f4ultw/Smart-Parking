package mx.smartparking.api.operadores;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;
import mx.smartparking.api.activacion.PreparacionInvitacionOperador;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.empleados.coordinacion.EmpleadoEnlaceOperador;
import mx.smartparking.api.empleados.coordinacion.PuertoEmpleadosOperador;
import mx.smartparking.api.persistencia.RepositorioOperadores;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
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
class ServicioAdministracionOperadoresTest {

    private static final UUID OPERADOR_ID = UUID.fromString("8c3d3c62-e588-48dc-96ec-6d9d98c70dcb");
    private static final UUID DUENO_ID = UUID.fromString("85a4bff5-eae0-4ba7-b509-24f4071e05fa");
    private static final String CLAVE = "c0d0f0de-7641-4c78-b6a6-e26904c271e8";
    private static final Instant CREADA = Instant.parse("2026-10-20T10:00:00Z");

    @Mock
    private RepositorioOperadores repositorio;
    @Mock
    private PuertoInvitacionesAdministracion invitaciones;
    @Mock
    private GestorSesionesPropietario sesiones;
    @Mock
    private ServicioEventosAdministracion eventos;
    @Mock
    private PuertoEmpleadosOperador empleados;

    private List<String> orden;
    private ServicioAdministracionOperadores servicio;

    @BeforeEach
    void preparar() {
        orden = new ArrayList<>();
        servicio = new ServicioAdministracionOperadores(
                repositorio, invitaciones, sesiones, eventos, administradorTransacciones());
        servicio.establecerEmpleados(empleados);
    }

    @Test
    void desactivacionInvalidaTokensDentroDeLaTransaccionYRevocaDespuesDelCommit() {
        CuentaOperadorAdministrable activa = cuenta(EstadoCuentaOperador.ACTIVA, 4);
        CuentaOperadorAdministrable inactiva = cuenta(EstadoCuentaOperador.INACTIVA, 5);
        when(repositorio.bloquearCuentaAdministrable(OPERADOR_ID)).thenAnswer(llamada -> {
            orden.add("bloquear");
            return Optional.of(activa);
        });
        when(repositorio.actualizarEstado(OPERADOR_ID, EstadoCuentaOperador.INACTIVA, 4, 5))
                .thenAnswer(llamada -> {
                    orden.add("actualizar");
                    return inactiva;
                });
        when(repositorio.buscarCuentaAdministrable(OPERADOR_ID)).thenReturn(Optional.of(inactiva));
        when(invitaciones.consultar(OPERADOR_ID)).thenReturn(proyeccion(false));
        org.mockito.Mockito.doAnswer(llamada -> {
            orden.add("invalidar");
            return null;
        }).when(invitaciones).invalidarPendientes(OPERADOR_ID);
        org.mockito.Mockito.doAnswer(llamada -> {
            orden.add("revocar");
            return null;
        }).when(sesiones).revocarCuenta(OPERADOR_ID);
        org.mockito.Mockito.doAnswer(llamada -> {
            orden.add("evento");
            return null;
        }).when(eventos).publicarDirectorioOperadorActualizado();

        DetalleOperadorVersionado resultado = servicio.cambiarEstado(
                OPERADOR_ID, "INACTIVA", "\"4\"", null, dueno());

        assertEquals(EstadoCuentaOperador.INACTIVA, resultado.detalle().estado());
        assertEquals(5, resultado.revisionAcceso());
        assertEquals(true, resultado.detalle().puedeReactivar());
        assertEquals(List.of("inicio", "bloquear", "invalidar", "actualizar", "commit",
                "revocar", "evento", "inicio", "commit"), orden);
        verify(invitaciones, never()).prepararReactivacion(any(), any(), any());
    }

    @Test
    void reactivacionLegacyRequiereConciliacion() {
        CuentaOperadorAdministrable inactiva = cuenta(EstadoCuentaOperador.INACTIVA, 7);
        when(repositorio.bloquearCuentaAdministrable(OPERADOR_ID)).thenReturn(Optional.of(inactiva));

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () -> servicio.cambiarEstado(
                OPERADOR_ID, "PENDIENTE", "\"7\"", CLAVE, dueno()));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertEquals("EMPLEADO_REQUERIDO", error.codigo());
        verify(invitaciones, never()).prepararReactivacion(any(), any(), any());
        verify(invitaciones, never()).enviarReactivacion(any());
    }

    @Test
    void reactivacionVinculadaPreparaInvitacionYAvanzaRevisionEmpleado() {
        long empleadoId = 42;
        CuentaOperadorAdministrable inactiva = cuenta(EstadoCuentaOperador.INACTIVA, 7, empleadoId);
        CuentaOperadorAdministrable pendiente = cuenta(EstadoCuentaOperador.PENDIENTE, 8, empleadoId);
        EmpleadoEnlaceOperador empleado = new EmpleadoEnlaceOperador(
                empleadoId, "E-0042", "ACTIVO", 5, "operador@example.test", "operador@example.test");
        when(repositorio.empleadoId(OPERADOR_ID)).thenReturn(Optional.of(empleadoId));
        when(empleados.bloquearPorId(empleadoId)).thenReturn(Optional.of(empleado));
        when(empleados.incrementarRevision(empleadoId, 5)).thenAnswer(llamada -> {
            orden.add("revision-empleado");
            return true;
        });
        PreparacionInvitacionOperador preparacion = org.mockito.Mockito.mock(PreparacionInvitacionOperador.class);
        when(repositorio.bloquearCuentaAdministrable(OPERADOR_ID)).thenAnswer(llamada -> {
            orden.add("bloquear");
            return Optional.of(inactiva);
        });
        when(invitaciones.reactivacionRepetida(OPERADOR_ID, CLAVE)).thenReturn(false);
        when(invitaciones.prepararReactivacion(OPERADOR_ID, "operador@example.test", CLAVE))
                .thenAnswer(llamada -> {
                    orden.add("preparar-invitacion");
                    return preparacion;
                });
        when(repositorio.actualizarEstado(OPERADOR_ID, EstadoCuentaOperador.PENDIENTE, 7, 8))
                .thenAnswer(llamada -> {
                    orden.add("actualizar");
                    return pendiente;
                });
        when(repositorio.buscarCuentaAdministrable(OPERADOR_ID)).thenReturn(Optional.of(pendiente));
        when(invitaciones.enviarReactivacion(preparacion)).thenAnswer(llamada -> {
            orden.add("correo");
            return EstadoEnvioInvitacion.ENVIADO;
        });
        when(invitaciones.consultar(OPERADOR_ID)).thenReturn(proyeccion(false));
        org.mockito.Mockito.doAnswer(llamada -> {
            orden.add("evento-empleado");
            return null;
        }).when(eventos).publicarDirectorioActualizado();
        org.mockito.Mockito.doAnswer(llamada -> {
            orden.add("evento-operador");
            return null;
        }).when(eventos).publicarDirectorioOperadorActualizado();

        DetalleOperadorVersionado resultado = servicio.cambiarEstado(
                OPERADOR_ID, "PENDIENTE", "\"7\"", CLAVE, dueno());

        assertEquals(EstadoCuentaOperador.PENDIENTE, resultado.detalle().estado());
        assertEquals(8, resultado.revisionAcceso());
        assertEquals(List.of("inicio", "bloquear", "preparar-invitacion", "actualizar", "revision-empleado", "commit",
                "evento-empleado", "evento-operador", "correo", "inicio", "commit"), orden);
    }

    @Test
    void replayDeReactivacionConEtagAnteriorNoVuelveAEnviarNiCambiaRevision() {
        CuentaOperadorAdministrable pendiente = cuenta(EstadoCuentaOperador.PENDIENTE, 9);
        when(repositorio.bloquearCuentaAdministrable(OPERADOR_ID)).thenReturn(Optional.of(pendiente));
        when(invitaciones.reactivacionRepetida(OPERADOR_ID, CLAVE)).thenReturn(true);
        when(repositorio.buscarCuentaAdministrable(OPERADOR_ID)).thenReturn(Optional.of(pendiente));
        when(invitaciones.consultar(OPERADOR_ID)).thenReturn(proyeccion(false));

        DetalleOperadorVersionado resultado = servicio.cambiarEstado(
                OPERADOR_ID, "PENDIENTE", "\"8\"", CLAVE, dueno());

        assertEquals(9, resultado.revisionAcceso());
        verify(repositorio, never()).actualizarEstado(any(), any(), org.mockito.ArgumentMatchers.anyLong(),
                org.mockito.ArgumentMatchers.anyLong());
        verify(invitaciones, never()).enviarReactivacion(any());
        verify(eventos, never()).publicarDirectorioOperadorActualizado();
    }

    @Test
    void revisionObsoletaNoInvalidaTokensNiCambiaLaCuenta() {
        CuentaOperadorAdministrable activa = cuenta(EstadoCuentaOperador.ACTIVA, 3);
        when(repositorio.bloquearCuentaAdministrable(OPERADOR_ID)).thenReturn(Optional.of(activa));

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () -> servicio.cambiarEstado(
                OPERADOR_ID, "INACTIVA", "\"2\"", null, dueno()));

        assertEquals(HttpStatus.PRECONDITION_FAILED, error.estadoHttp());
        assertEquals("REVISION_OBSOLETA", error.codigo());
        verify(invitaciones, never()).invalidarPendientes(OPERADOR_ID);
        verify(repositorio, never()).actualizarEstado(any(), any(), org.mockito.ArgumentMatchers.anyLong(),
                org.mockito.ArgumentMatchers.anyLong());
        verify(eventos, never()).publicarDirectorioOperadorActualizado();
    }

    private CuentaOperadorAdministrable cuenta(EstadoCuentaOperador estado, long revision) {
        return cuenta(estado, revision, null);
    }

    private CuentaOperadorAdministrable cuenta(EstadoCuentaOperador estado, long revision, Long empleadoId) {
        return new CuentaOperadorAdministrable(
                OPERADOR_ID, "Ana", "López", null, "operador@example.test", estado, CREADA, revision, empleadoId);
    }

    private static ProyeccionInvitacionOperador proyeccion(boolean puedeReactivar) {
        return new ProyeccionInvitacionOperador(
                "CONSUMIDA", CREADA, CREADA.plusSeconds(7_200), CREADA.plusSeconds(100),
                null, 3, false, null, 3, puedeReactivar);
    }

    private static PrincipalPropietario dueno() {
        return new PrincipalPropietario(DUENO_ID, RolCuenta.DUENO, 1, 1, "dueno@example.test");
    }

    private PlatformTransactionManager administradorTransacciones() {
        return new PlatformTransactionManager() {
            @Override
            public TransactionStatus getTransaction(TransactionDefinition definicion) {
                orden.add("inicio");
                return new SimpleTransactionStatus();
            }

            @Override
            public void commit(TransactionStatus estado) {
                orden.add("commit");
            }

            @Override
            public void rollback(TransactionStatus estado) {
                orden.add("rollback");
            }
        };
    }
}
