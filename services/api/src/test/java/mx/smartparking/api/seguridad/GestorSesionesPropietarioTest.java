package mx.smartparking.api.seguridad;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import jakarta.servlet.http.HttpSession;
import jakarta.servlet.http.HttpSessionEvent;
import java.util.Set;
import org.springframework.context.ApplicationEventPublisher;
import org.junit.jupiter.api.Test;

class GestorSesionesPropietarioTest {

    @Test
    void revocaSoloLasSesionesDeLaRevisionIndicada() {
        GestorSesionesPropietario gestor = new GestorSesionesPropietario();
        HttpSession sesionVigente = crearSesion("sesion-vigente");
        HttpSession sesionAnterior = crearSesion("sesion-anterior");
        gestor.registrar(sesionVigente, 8L);
        gestor.registrar(sesionAnterior, 7L);

        gestor.revocarRevision(7L);

        assertTrue(gestor.estaRegistrada("sesion-vigente", 8L));
        assertFalse(gestor.estaRegistrada("sesion-anterior", 7L));
        verify(sesionAnterior).invalidate();
        verify(sesionVigente, never()).invalidate();
    }

    @Test
    void revocarTodasInvalidaTodasLasSesionesRegistradas() {
        GestorSesionesPropietario gestor = new GestorSesionesPropietario();
        HttpSession sesionUno = crearSesion("sesion-uno");
        HttpSession sesionDos = crearSesion("sesion-dos");
        gestor.registrar(sesionUno, 2L);
        gestor.registrar(sesionDos, 3L);

        gestor.revocarTodas();

        assertFalse(gestor.estaRegistrada("sesion-uno", 2L));
        assertFalse(gestor.estaRegistrada("sesion-dos", 3L));
        verify(sesionUno).invalidate();
        verify(sesionDos).invalidate();
    }

    @Test
    void descartaSesionExpiradaQueYaNoPuedeConsultarse() {
        GestorSesionesPropietario gestor = new GestorSesionesPropietario();
        HttpSession sesionExpirada = mock(HttpSession.class);
        when(sesionExpirada.getId()).thenReturn("sesion-expirada");
        when(sesionExpirada.getLastAccessedTime()).thenThrow(new IllegalStateException("sesión expirada"));
        gestor.registrar(sesionExpirada, 11L);

        assertFalse(gestor.estaRegistrada("sesion-expirada", 11L));
        assertFalse(gestor.estaRegistrada("sesion-expirada", 11L));
    }

    @Test
    void exponeSoloHuellasYNotificaLaRevocacionSinIdClaro() {
        ApplicationEventPublisher eventos = mock(ApplicationEventPublisher.class);
        GestorSesionesPropietario gestor = new GestorSesionesPropietario(eventos);
        HttpSession sesion = crearSesion("id-claro-de-sesion");
        String huella = HuellaSesionPropietario.calcular("id-claro-de-sesion");
        gestor.registrar(sesion, 12L);

        assertEquals(Set.of(huella), gestor.huellasSesionesActivas());
        gestor.olvidar(sesion);

        verify(eventos).publishEvent(new SesionPropietarioRevocada(huella));
        assertTrue(gestor.huellasSesionesActivas().isEmpty());
    }

    @Test
    void vencimientoNaturalRetiraLaSesionYEmiteSoloSuHuella() {
        ApplicationEventPublisher eventos = mock(ApplicationEventPublisher.class);
        GestorSesionesPropietario gestor = new GestorSesionesPropietario(eventos);
        HttpSession sesion = crearSesion("sesion-vencida");
        gestor.registrar(sesion, 13L);

        new EscuchaFinSesionPropietario(gestor).sessionDestroyed(new HttpSessionEvent(sesion));

        assertTrue(gestor.huellasSesionesActivas().isEmpty());
        verify(eventos).publishEvent(new SesionPropietarioRevocada(
                HuellaSesionPropietario.calcular("sesion-vencida")));
    }

    private HttpSession crearSesion(String id) {
        HttpSession sesion = mock(HttpSession.class);
        when(sesion.getId()).thenReturn(id);
        when(sesion.getLastAccessedTime()).thenReturn(1L);
        return sesion;
    }
}
