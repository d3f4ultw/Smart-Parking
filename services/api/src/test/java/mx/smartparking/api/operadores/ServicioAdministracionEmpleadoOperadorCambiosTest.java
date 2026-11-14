package mx.smartparking.api.operadores;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import java.util.List;
import java.util.Optional;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;
import mx.smartparking.api.activacion.PreparacionInvitacionOperador;
import mx.smartparking.api.empleados.coordinacion.EmpleadoEnlaceOperador;
import mx.smartparking.api.empleados.coordinacion.ResultadoAccionEmpleadoOperador;
import mx.smartparking.api.empleados.coordinacion.ResultadoCambioCorreoEmpleadoOperador;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class ServicioAdministracionEmpleadoOperadorCambiosTest extends ServicioAdministracionEmpleadoOperadorTestSupport {

    @Test
    void correoActivoConservaAccesoYRevocaSesionTrasCommit() {
        EmpleadoEnlaceOperador empleado = empleado("ACTIVO", 7, "ana@example.test");
        CuentaOperadorAdministrable cuenta = cuenta(EstadoCuentaOperador.ACTIVA, 4, "ana@example.test", EMPLEADO_ID);
        CuentaOperadorAdministrable actualizada = cuenta(EstadoCuentaOperador.ACTIVA, 5, "nuevo@example.test", EMPLEADO_ID);
        when(empleados.consultarPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(acciones.reservar(eq(DUENO_ID), anyString(), anyString(), eq("CAMBIAR_CORREO"), eq(EMPLEADO_ID)))
                .thenReturn(true);
        when(empleados.bloquearPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(operadores.bloquearCuentaVinculada(EMPLEADO_ID)).thenReturn(Optional.of(cuenta));
        when(operadores.correoReservado("nuevo@example.test", OPERADOR_ID)).thenReturn(false);
        when(operadores.actualizarCorreo(OPERADOR_ID, "nuevo@example.test", "nuevo@example.test", 4))
                .thenReturn(actualizada);
        when(empleados.actualizarCorreoYRevision(EMPLEADO_ID, "nuevo@example.test", "nuevo@example.test", 7))
                .thenReturn(true);
        doAnswer(llamada -> {
            assertEquals(true, transaccionConfirmada);
            orden.add("revocar-sesion");
            return null;
        }).when(sesiones).revocarCuenta(OPERADOR_ID);
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

        ResultadoCambioCorreoEmpleadoOperador resultado = servicio.cambiarCorreo(
                Long.toString(EMPLEADO_ID), " Nuevo@Example.Test ", "\"7\"", CLAVE, dueno());

        assertEquals("nuevo@example.test", resultado.correo());
        assertEquals("8", resultado.revisionEmpleado());
        assertEquals("ACTIVA", resultado.estadoOperador());
        assertEquals(List.of("inicio", "commit", "revocar-sesion", "sse-empleados", "sse-operadores"), orden);
        verify(invitaciones).invalidarPendientes(OPERADOR_ID);
        verify(invitaciones, never()).prepararCambioCorreo(any(), anyString(), anyString());
        verify(operadores).actualizarCorreo(OPERADOR_ID, "nuevo@example.test", "nuevo@example.test", 4);
        verify(sesiones).revocarCuenta(OPERADOR_ID);
        verify(activacion, never()).enviarInicial(any());
        verify(invitaciones, never()).enviarCambioCorreo(any());
    }

    @Test
    void cambioDeCorreoPendienteSustituyeTokenYEntregaTrasCommit() {
        EmpleadoEnlaceOperador empleado = empleado("ACTIVO", 8, "ana@example.test");
        CuentaOperadorAdministrable cuenta = cuenta(EstadoCuentaOperador.PENDIENTE, 4,
                "ana@example.test", EMPLEADO_ID);
        CuentaOperadorAdministrable actualizada = cuenta(EstadoCuentaOperador.PENDIENTE, 5,
                "nuevo@example.test", EMPLEADO_ID);
        PreparacionInvitacionOperador preparacion = org.mockito.Mockito.mock(PreparacionInvitacionOperador.class);
        when(empleados.consultarPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(acciones.reservar(eq(DUENO_ID), anyString(), anyString(), eq("CAMBIAR_CORREO"), eq(EMPLEADO_ID)))
                .thenReturn(true);
        when(empleados.bloquearPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(operadores.bloquearCuentaVinculada(EMPLEADO_ID)).thenReturn(Optional.of(cuenta));
        when(operadores.correoReservado("nuevo@example.test", OPERADOR_ID)).thenReturn(false);
        when(invitaciones.prepararCambioCorreo(OPERADOR_ID, "nuevo@example.test", CLAVE)).thenReturn(preparacion);
        when(operadores.actualizarCorreo(OPERADOR_ID, "nuevo@example.test", "nuevo@example.test", 4))
                .thenReturn(actualizada);
        when(empleados.actualizarCorreoYRevision(EMPLEADO_ID, "nuevo@example.test", "nuevo@example.test", 8))
                .thenReturn(true);
        when(invitaciones.enviarCambioCorreo(preparacion)).thenAnswer(llamada -> {
            assertEquals(true, transaccionConfirmada);
            orden.add("smtp");
            return EstadoEnvioInvitacion.DESCONOCIDO;
        });

        ResultadoCambioCorreoEmpleadoOperador resultado = servicio.cambiarCorreo(
                Long.toString(EMPLEADO_ID), "nuevo@example.test", "\"8\"", CLAVE, dueno());

        assertEquals("9", resultado.revisionEmpleado());
        assertEquals("DESCONOCIDO", resultado.estadoInvitacion());
        assertEquals(List.of("inicio", "commit", "smtp"), orden);
        verify(invitaciones).prepararCambioCorreo(OPERADOR_ID, "nuevo@example.test", CLAVE);
        verify(invitaciones).enviarCambioCorreo(preparacion);
        verify(acciones).actualizarEstadoEnvio(eq(DUENO_ID), anyString(), eq("DESCONOCIDO"));
        verify(sesiones, never()).revocarCuenta(OPERADOR_ID);
    }

    @Test
    void desactivarAccesoVinculadoRevocaSesionYAvanzaAmbasRevisiones() {
        EmpleadoEnlaceOperador empleado = empleado("ACTIVO", 5, "ana@example.test");
        CuentaOperadorAdministrable cuenta = cuenta(EstadoCuentaOperador.ACTIVA, 6,
                "ana@example.test", EMPLEADO_ID);
        CuentaOperadorAdministrable inactiva = cuenta(EstadoCuentaOperador.INACTIVA, 7,
                "ana@example.test", EMPLEADO_ID);
        when(empleados.consultarPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(acciones.reservar(eq(DUENO_ID), anyString(), anyString(), eq("DESACTIVAR"), eq(EMPLEADO_ID)))
                .thenReturn(true);
        when(empleados.bloquearPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(operadores.bloquearCuentaVinculada(EMPLEADO_ID)).thenReturn(Optional.of(cuenta));
        when(operadores.actualizarEstado(OPERADOR_ID, EstadoCuentaOperador.INACTIVA, 6, 7))
                .thenReturn(inactiva);
        when(empleados.incrementarRevision(EMPLEADO_ID, 5)).thenReturn(true);
        doAnswer(llamada -> {
            assertEquals(true, transaccionConfirmada);
            orden.add("revocar-sesion");
            return null;
        }).when(sesiones).revocarCuenta(OPERADOR_ID);
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

        ResultadoAccionEmpleadoOperador resultado = servicio.desactivarAcceso(
                Long.toString(EMPLEADO_ID), "\"5\"", CLAVE, dueno());

        assertEquals("6", resultado.revisionEmpleado());
        assertEquals("INACTIVA", resultado.estadoOperador());
        assertEquals(List.of("inicio", "commit", "revocar-sesion", "sse-empleados", "sse-operadores"), orden);
        verify(invitaciones).invalidarPendientes(OPERADOR_ID);
        verify(operadores).actualizarEstado(OPERADOR_ID, EstadoCuentaOperador.INACTIVA, 6, 7);
        verify(empleados).incrementarRevision(EMPLEADO_ID, 5);
        verify(acciones).completar(eq(DUENO_ID), anyString(), eq(OPERADOR_ID), eq("INACTIVA"), eq(6L), eq(null));
    }
}
