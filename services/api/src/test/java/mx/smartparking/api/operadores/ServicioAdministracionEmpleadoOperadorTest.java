package mx.smartparking.api.operadores;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;
import mx.smartparking.api.activacion.PreparacionInvitacionOperador;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.empleados.coordinacion.EmpleadoEnlaceOperador;
import mx.smartparking.api.empleados.coordinacion.ResultadoAccionEmpleadoOperador;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.ArgumentCaptor;

@ExtendWith(MockitoExtension.class)
class ServicioAdministracionEmpleadoOperadorTest extends ServicioAdministracionEmpleadoOperadorTestSupport {

    @Test
    void promocionCreaCuentaVinculadaYEnviaSoloTrasCommit() {
        EmpleadoEnlaceOperador empleado = empleado("ACTIVO", 3, "ana@example.test");
        PreparacionInvitacionOperador preparacion = org.mockito.Mockito.mock(PreparacionInvitacionOperador.class);
        when(empleados.consultarPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(acciones.reservar(eq(DUENO_ID), anyString(), anyString(), eq("PROMOVER"), eq(EMPLEADO_ID)))
                .thenReturn(true);
        when(empleados.bloquearPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(operadores.bloquearCuentaVinculada(EMPLEADO_ID)).thenReturn(Optional.empty());
        when(operadores.correoReservado("ana@example.test", null)).thenReturn(false);
        when(operadores.crearOperadorVinculado(any(UUID.class), eq(EMPLEADO_ID)))
                .thenAnswer(llamada -> llamada.getArgument(0));
        when(activacion.prepararInicial(any(UUID.class), eq("ana@example.test"))).thenReturn(preparacion);
        when(empleados.incrementarRevision(EMPLEADO_ID, 3)).thenReturn(true);
        when(activacion.enviarInicial(preparacion)).thenAnswer(llamada -> {
            assertEquals(true, transaccionConfirmada);
            orden.add("smtp");
            return EstadoEnvioInvitacion.ENVIADO;
        });
        doAnswer(llamada -> {
            assertEquals(true, transaccionConfirmada);
            orden.add("sse-empleados");
            return null;
        }).when(eventos).publicarDirectorioActualizado();
        doAnswer(llamada -> {
            assertEquals(true, transaccionConfirmada);
            orden.add("sse-operadores");
            return null;
        }).when(eventos).publicarDirectorioOperadorActualizado();

        ResultadoAccionEmpleadoOperador resultado = servicio.promocionar(
                Long.toString(EMPLEADO_ID), "\"3\"", CLAVE, dueno());

        assertEquals(Long.toString(EMPLEADO_ID), resultado.empleadoId());
        ArgumentCaptor<UUID> operadorCreado = ArgumentCaptor.forClass(UUID.class);
        verify(operadores).crearOperadorVinculado(operadorCreado.capture(), eq(EMPLEADO_ID));
        assertEquals(operadorCreado.getValue(), resultado.operadorId());
        assertEquals("PENDIENTE", resultado.estadoOperador());
        assertEquals("4", resultado.revisionEmpleado());
        assertEquals("ENVIADO", resultado.estadoInvitacion());
        verify(acciones).actualizarEstadoEnvio(eq(DUENO_ID), anyString(), eq("ENVIADO"));
        assertEquals(List.of("inicio", "commit", "sse-empleados", "sse-operadores", "smtp"), orden);
    }

    @Test
    void promocionActualizaCorreoYCuentaEnLaMismaTransaccion() {
        EmpleadoEnlaceOperador empleado = empleado("ACTIVO", 3, null);
        PreparacionInvitacionOperador preparacion = org.mockito.Mockito.mock(PreparacionInvitacionOperador.class);
        when(empleados.consultarPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(acciones.reservar(eq(DUENO_ID), anyString(), anyString(), eq("PROMOVER"), eq(EMPLEADO_ID)))
                .thenReturn(true);
        when(empleados.bloquearPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(operadores.bloquearCuentaVinculada(EMPLEADO_ID)).thenReturn(Optional.empty());
        when(operadores.correoReservado("nuevo@example.test", null)).thenReturn(false);
        when(empleados.actualizarCorreoYRevision(EMPLEADO_ID, "nuevo@example.test", "nuevo@example.test", 3))
                .thenReturn(true);
        when(operadores.crearOperadorVinculado(any(UUID.class), eq(EMPLEADO_ID)))
                .thenAnswer(llamada -> llamada.getArgument(0));
        when(activacion.prepararInicial(any(UUID.class), eq("nuevo@example.test"))).thenReturn(preparacion);
        when(activacion.enviarInicial(preparacion)).thenAnswer(llamada -> {
            assertEquals(true, transaccionConfirmada);
            orden.add("smtp");
            return EstadoEnvioInvitacion.ENVIADO;
        });

        ResultadoAccionEmpleadoOperador resultado = servicio.promocionar(
                Long.toString(EMPLEADO_ID), " Nuevo@Example.Test ", "\"3\"", CLAVE, dueno());

        assertEquals("4", resultado.revisionEmpleado());
        assertEquals("ENVIADO", resultado.estadoInvitacion());
        verify(empleados).actualizarCorreoYRevision(
                EMPLEADO_ID, "nuevo@example.test", "nuevo@example.test", 3);
        verify(empleados, never()).incrementarRevision(EMPLEADO_ID, 3);
        verify(operadores).crearOperadorVinculado(any(UUID.class), eq(EMPLEADO_ID));
        verify(activacion).prepararInicial(any(UUID.class), eq("nuevo@example.test"));
        verify(acciones).actualizarEstadoEnvio(eq(DUENO_ID), anyString(), eq("ENVIADO"));
        assertEquals(List.of("inicio", "commit", "smtp"), orden);
    }

    @Test
    void fallaAlPrepararInvitacionRevierteCorreoYAltaAntesDePublicar() {
        EmpleadoEnlaceOperador empleado = empleado("ACTIVO", 3, null);
        when(empleados.consultarPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(acciones.reservar(eq(DUENO_ID), anyString(), anyString(), eq("PROMOVER"), eq(EMPLEADO_ID)))
                .thenReturn(true);
        when(empleados.bloquearPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(operadores.bloquearCuentaVinculada(EMPLEADO_ID)).thenReturn(Optional.empty());
        when(operadores.correoReservado("nuevo@example.test", null)).thenReturn(false);
        when(empleados.actualizarCorreoYRevision(EMPLEADO_ID, "nuevo@example.test", "nuevo@example.test", 3))
                .thenReturn(true);
        when(operadores.crearOperadorVinculado(any(UUID.class), eq(EMPLEADO_ID)))
                .thenAnswer(llamada -> llamada.getArgument(0));
        when(activacion.prepararInicial(any(UUID.class), eq("nuevo@example.test")))
                .thenThrow(new IllegalStateException("fallo de prueba"));

        assertThrows(IllegalStateException.class, () -> servicio.promocionar(
                Long.toString(EMPLEADO_ID), "nuevo@example.test", "\"3\"", CLAVE, dueno()));

        assertEquals(List.of("inicio", "rollback"), orden);
        verify(empleados).actualizarCorreoYRevision(
                EMPLEADO_ID, "nuevo@example.test", "nuevo@example.test", 3);
        verify(operadores).crearOperadorVinculado(any(UUID.class), eq(EMPLEADO_ID));
        verify(activacion, never()).enviarInicial(any());
        verify(acciones, never()).actualizarEstadoEnvio(any(), anyString(), anyString());
        verify(eventos, never()).publicarDirectorioActualizado();
        verify(eventos, never()).publicarDirectorioOperadorActualizado();
    }

    @ParameterizedTest
    @EnumSource(value = EstadoCuentaOperador.class, names = {"ACTIVA", "PENDIENTE"})
    void promocionNoDuplicaUnaCuentaActivaOVigenteAunqueSeEnvieOtroCorreo(EstadoCuentaOperador estado) {
        EmpleadoEnlaceOperador empleado = empleado("ACTIVO", 3, "ana@example.test");
        CuentaOperadorAdministrable cuenta = cuenta(estado, 1, "ana@example.test", EMPLEADO_ID);
        when(empleados.consultarPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(acciones.reservar(eq(DUENO_ID), anyString(), anyString(), eq("PROMOVER"), eq(EMPLEADO_ID)))
                .thenReturn(true);
        when(empleados.bloquearPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(operadores.bloquearCuentaVinculada(EMPLEADO_ID)).thenReturn(Optional.of(cuenta));

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () -> servicio.promocionar(
                Long.toString(EMPLEADO_ID), "otro@example.test", "\"3\"", CLAVE, dueno()));

        assertEquals("OPERADOR_YA_VINCULADO", error.codigo());
        verify(empleados, never()).actualizarCorreoYRevision(anyLong(), anyString(), anyString(), anyLong());
        verify(operadores, never()).crearOperadorVinculado(any(), anyLong());
        verify(activacion, never()).prepararInicial(any(), anyString());
        verify(eventos, never()).publicarDirectorioOperadorActualizado();
    }

    @Test
    void promocionRechazaCorreoReservadoAntesDeActualizarEmpleado() {
        EmpleadoEnlaceOperador empleado = empleado("ACTIVO", 3, null);
        when(empleados.consultarPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(acciones.reservar(eq(DUENO_ID), anyString(), anyString(), eq("PROMOVER"), eq(EMPLEADO_ID)))
                .thenReturn(true);
        when(empleados.bloquearPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(operadores.bloquearCuentaVinculada(EMPLEADO_ID)).thenReturn(Optional.empty());
        when(operadores.correoReservado("usado@example.test", null)).thenReturn(true);

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () -> servicio.promocionar(
                Long.toString(EMPLEADO_ID), "usado@example.test", "\"3\"", CLAVE, dueno()));

        assertEquals("CORREO_EN_USO", error.codigo());
        verify(empleados, never()).actualizarCorreoYRevision(anyLong(), anyString(), anyString(), anyLong());
        verify(operadores, never()).crearOperadorVinculado(any(), anyLong());
        verify(activacion, never()).prepararInicial(any(), anyString());
        verify(eventos, never()).publicarDirectorioActualizado();
        verify(eventos, never()).publicarDirectorioOperadorActualizado();
    }
}
