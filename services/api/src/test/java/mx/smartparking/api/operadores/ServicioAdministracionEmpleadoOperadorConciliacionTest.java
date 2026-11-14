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
import java.util.Optional;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.empleados.coordinacion.EmpleadoEnlaceOperador;
import mx.smartparking.api.empleados.coordinacion.ResultadoAccionEmpleadoOperador;
import mx.smartparking.api.empleados.coordinacion.ResultadoCambioCorreoEmpleadoOperador;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;

@ExtendWith(MockitoExtension.class)
class ServicioAdministracionEmpleadoOperadorConciliacionTest extends ServicioAdministracionEmpleadoOperadorTestSupport {

    @Test
    void conciliacionSinConfirmacionDeCorreoNoModificaNingunaIdentidad() {
        EmpleadoEnlaceOperador empleado = empleado("ACTIVO", 3, null);
        CuentaOperadorAdministrable legada = cuenta(EstadoCuentaOperador.ACTIVA, 6, "legado@example.test", null);
        prepararConciliacion(empleado, legada);

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () -> servicio.vincular(
                Long.toString(EMPLEADO_ID), OPERADOR_ID, "6", false, "\"3\"", CLAVE, dueno()));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertEquals("CONFIRMACION_CORREO_REQUERIDA", error.codigo());
        verify(empleados, never()).actualizarCorreoYRevision(anyLong(), any(), any(), anyLong());
        verify(operadores, never()).vincularCuenta(any(), anyLong(), anyLong());
        verify(acciones, never()).completar(any(), anyString(), any(), any(), anyLong(), any());
        verify(activacion, never()).prepararInicial(any(), anyString());
    }

    @Test
    void conciliacionConfirmadaCopiaSoloElCorreoSinReemitirNiCambiarContrasena() {
        EmpleadoEnlaceOperador empleado = empleado("ACTIVO", 3, null);
        CuentaOperadorAdministrable legada = cuenta(EstadoCuentaOperador.ACTIVA, 6, "legado@example.test", null);
        CuentaOperadorAdministrable vinculada = cuenta(EstadoCuentaOperador.ACTIVA, 7, "legado@example.test", EMPLEADO_ID);
        prepararConciliacion(empleado, legada);
        when(empleados.actualizarCorreoYRevision(EMPLEADO_ID,
                "legado@example.test", "legado@example.test", 3)).thenReturn(true);
        when(operadores.vincularCuenta(OPERADOR_ID, EMPLEADO_ID, 6)).thenReturn(vinculada);
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

        ResultadoAccionEmpleadoOperador resultado = servicio.vincular(
                Long.toString(EMPLEADO_ID), OPERADOR_ID, "6", true, "\"3\"", CLAVE, dueno());

        assertEquals(Long.toString(EMPLEADO_ID), resultado.empleadoId());
        assertEquals("4", resultado.revisionEmpleado());
        assertEquals(OPERADOR_ID, resultado.operadorId());
        assertEquals("ACTIVA", resultado.estadoOperador());
        verify(operadores).vincularCuenta(OPERADOR_ID, EMPLEADO_ID, 6);
        verify(empleados).actualizarCorreoYRevision(
                EMPLEADO_ID, "legado@example.test", "legado@example.test", 3);
        verify(invitaciones, never()).prepararCambioCorreo(any(), anyString(), anyString());
        verify(invitaciones, never()).enviarCambioCorreo(any());
        verify(activacion, never()).prepararInicial(any(), anyString());
        verify(sesiones).revocarCuenta(OPERADOR_ID);
    }

    @Test
    void vinculaSinCorreoCuandoAmbasIdentidadesCarecenDeCorreoYLaCuentaEsInactiva() {
        EmpleadoEnlaceOperador empleado = empleado("INACTIVO", 3, null);
        CuentaOperadorAdministrable legada = cuenta(EstadoCuentaOperador.INACTIVA, 6, null, null);
        CuentaOperadorAdministrable vinculada = cuenta(EstadoCuentaOperador.INACTIVA, 7, null, EMPLEADO_ID);
        prepararConciliacion(empleado, legada);
        when(operadores.vincularCuenta(OPERADOR_ID, EMPLEADO_ID, 6)).thenReturn(vinculada);
        when(empleados.incrementarRevision(EMPLEADO_ID, 3)).thenReturn(true);

        ResultadoAccionEmpleadoOperador resultado = servicio.vincular(
                Long.toString(EMPLEADO_ID), OPERADOR_ID, "6", false, "\"3\"", CLAVE, dueno());

        assertEquals("4", resultado.revisionEmpleado());
        assertEquals("INACTIVA", resultado.estadoOperador());
        verify(empleados, never()).actualizarCorreoYRevision(anyLong(), any(), any(), anyLong());
        verify(empleados).incrementarRevision(EMPLEADO_ID, 3);
        verify(invitaciones, never()).prepararReactivacion(any(), any(), any());
        verify(invitaciones, never()).prepararCambioCorreo(any(), anyString(), anyString());
        verify(sesiones, never()).revocarCuenta(OPERADOR_ID);
    }

    @Test
    void replayDeCambioCorreoDevuelveElCorreoDelMismoRequestSinNuevaMutacion() {
        EmpleadoEnlaceOperador empleado = empleado("ACTIVO", 9, "nuevo@example.test");
        when(empleados.consultarPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(acciones.reservar(eq(DUENO_ID), anyString(), anyString(), eq("CAMBIAR_CORREO"), eq(EMPLEADO_ID)))
                .thenReturn(false);
        when(acciones.bloquear(eq(DUENO_ID), anyString())).thenReturn(Optional.of(
                new AccionEmpleadoOperadorPersistida(
                        huella("CAMBIAR_CORREO", Long.toString(EMPLEADO_ID), "nuevo@example.test"),
                        "CAMBIAR_CORREO", EMPLEADO_ID, "COMPLETADA", OPERADOR_ID,
                        "ACTIVA", 8L, null)));

        ResultadoCambioCorreoEmpleadoOperador resultado = servicio.cambiarCorreo(
                Long.toString(EMPLEADO_ID), " Nuevo@Example.Test ", "\"7\"", CLAVE, dueno());

        assertEquals("nuevo@example.test", resultado.correo());
        assertEquals("8", resultado.revisionEmpleado());
        verify(empleados, never()).bloquearPorId(EMPLEADO_ID);
        verify(operadores, never()).actualizarCorreo(any(), anyString(), anyString(), anyLong());
        verify(invitaciones, never()).enviarCambioCorreo(any());
        verify(sesiones, never()).revocarCuenta(OPERADOR_ID);
    }

    @Test
    void mismaClaveReproduceReciboAntesDeValidarEtagObsoleto() {
        EmpleadoEnlaceOperador empleado = empleado("ACTIVO", 9, "ana@example.test");
        when(empleados.consultarPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(acciones.reservar(eq(DUENO_ID), anyString(), anyString(), eq("PROMOVER"), eq(EMPLEADO_ID)))
                .thenReturn(false);
        when(acciones.bloquear(eq(DUENO_ID), anyString())).thenReturn(Optional.of(
                new AccionEmpleadoOperadorPersistida(huellaPromocion(), "PROMOVER", EMPLEADO_ID,
                        "COMPLETADA", OPERADOR_ID, "PENDIENTE", 4L, "ENVIADO")));

        ResultadoAccionEmpleadoOperador resultado = servicio.promocionar(
                Long.toString(EMPLEADO_ID), "\"3\"", CLAVE, dueno());

        assertEquals("4", resultado.revisionEmpleado());
        assertEquals(OPERADOR_ID, resultado.operadorId());
        verify(empleados, never()).bloquearPorId(EMPLEADO_ID);
        verify(operadores, never()).crearOperadorVinculado(any(), anyLong());
        verify(activacion, never()).enviarInicial(any());
        verify(eventos, never()).publicarDirectorioOperadorActualizado();
    }
}
