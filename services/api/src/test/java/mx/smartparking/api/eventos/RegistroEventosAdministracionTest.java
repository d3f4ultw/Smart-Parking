package mx.smartparking.api.eventos;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.UUID;
import org.junit.jupiter.api.Test;

/** Verifica el cursor y el replay acotado del registro de invalidaciones. */
class RegistroEventosAdministracionTest {

    private static final UUID EPOCA = UUID.fromString("2d329f2c-e53c-47a9-8f22-76997aa50100");

    @Test
    void reproduceSoloLosEventosPosterioresRetenidos() {
        RegistroEventosAdministracion registro = new RegistroEventosAdministracion(EPOCA);
        String cursorInicial = registro.cursorActual();

        RegistroEventosAdministracion.Evento primero = registro.registrarCambio();
        RegistroEventosAdministracion.Evento segundo = registro.registrarCambio();
        RegistroEventosAdministracion.PlanReproduccion plan = registro.resolver(cursorInicial);

        assertFalse(plan.requiereResincronizacion());
        assertEquals(2, plan.eventos().size());
        assertEquals(primero, plan.eventos().getFirst());
        assertEquals(segundo, plan.eventos().getLast());
        assertEquals(segundo.cursor(), plan.cursorActual());
    }

    @Test
    void conservaElTipoDeCadaEventoAlReproducirElCursorCompartido() {
        RegistroEventosAdministracion registro = new RegistroEventosAdministracion(EPOCA);
        registro.registrarCambio(RegistroEventosAdministracion.NOMBRE_EVENTO_EMPLEADOS);
        registro.registrarCambio(RegistroEventosAdministracion.NOMBRE_EVENTO_OPERADORES);

        RegistroEventosAdministracion.PlanReproduccion plan = registro.resolver(registroCursorCero());

        assertEquals(RegistroEventosAdministracion.NOMBRE_EVENTO_EMPLEADOS,
                plan.eventos().getFirst().nombreEvento());
        assertEquals(RegistroEventosAdministracion.NOMBRE_EVENTO_OPERADORES,
                plan.eventos().getLast().nombreEvento());
        assertEquals(RegistroEventosAdministracion.NOMBRE_EVENTO_RESINCRONIZAR,
                registro.invalidacionActual().nombreEvento());
    }

    @Test
    void reproduceLaInvalidacionDeCapturaRfid1EnElCursorCompartido() {
        RegistroEventosAdministracion registro = new RegistroEventosAdministracion(EPOCA);
        String cursorInicial = registro.cursorActual();
        RegistroEventosAdministracion.Evento evento = registro.registrarCambio(
                RegistroEventosAdministracion.NOMBRE_EVENTO_CAPTURA_RFID1_ACTUALIZADA);

        RegistroEventosAdministracion.PlanReproduccion plan = registro.resolver(cursorInicial);

        assertEquals(1, plan.eventos().size());
        assertEquals("rfid1.captura.actualizada", evento.nombreEvento());
        assertEquals(evento.nombreEvento(), plan.eventos().getFirst().nombreEvento());
        assertEquals(evento.cursor(), plan.cursorActual());
    }

    @Test
    void resincronizaSiElCursorEsAjenoInvalidoFuturoOViejo() {
        RegistroEventosAdministracion registro = new RegistroEventosAdministracion(EPOCA);
        registro.registrarCambio();

        assertTrue(registro.resolver("no-es-un-cursor").requiereResincronizacion());
        assertTrue(registro.resolver(UUID.randomUUID() + ":0").requiereResincronizacion());
        assertTrue(registro.resolver(EPOCA + ":2").requiereResincronizacion());

        for (int indice = 0; indice < RegistroEventosAdministracion.CAPACIDAD_HISTORIAL; indice++) {
            registro.registrarCambio();
        }
        assertTrue(registro.resolver(EPOCA + ":0").requiereResincronizacion());
    }

    @Test
    void conservaComoMaximo256EventosYAceptaElCursorDeLaUltimaSecuenciaRetenida() {
        RegistroEventosAdministracion registro = new RegistroEventosAdministracion(EPOCA);
        for (int indice = 0; indice < RegistroEventosAdministracion.CAPACIDAD_HISTORIAL; indice++) {
            registro.registrarCambio();
        }

        RegistroEventosAdministracion.PlanReproduccion plan = registro.resolver(EPOCA + ":0");
        assertFalse(plan.requiereResincronizacion());
        assertEquals(RegistroEventosAdministracion.CAPACIDAD_HISTORIAL, plan.eventos().size());

        registro.registrarCambio();
        assertTrue(registro.resolver(EPOCA + ":0").requiereResincronizacion());
        assertEquals(RegistroEventosAdministracion.CAPACIDAD_HISTORIAL,
                registro.resolver(EPOCA + ":1").eventos().size());
    }

    private static String registroCursorCero() {
        return EPOCA + ":0";
    }
}
