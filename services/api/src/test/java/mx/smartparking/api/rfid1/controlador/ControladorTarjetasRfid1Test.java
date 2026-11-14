package mx.smartparking.api.rfid1.controlador;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.util.List;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.Pagina;
import mx.smartparking.api.rfid1.servicio.ServicioTarjetasRfid1;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.mock.web.MockHttpServletRequest;

class ControladorTarjetasRfid1Test {
    @Test
    void reenviaBusquedaAlServicioSinCambiarLaRespuesta() {
        ServicioTarjetasRfid1 servicio = mock(ServicioTarjetasRfid1.class);
        PrincipalPropietario principal = mock(PrincipalPropietario.class);
        Pagina pagina = new Pagina(List.of(), 2, 10, 0, 0);
        when(servicio.listar("MIXTO", "ACTIVA", "2", "Ana", principal)).thenReturn(pagina);
        MockHttpServletRequest solicitud = new MockHttpServletRequest();
        solicitud.addParameter("busqueda", "Ana");

        var respuesta = new ControladorTarjetasRfid1(servicio)
                .listar("MIXTO", "ACTIVA", "2", "Ana", solicitud, principal);

        assertSame(pagina, respuesta.getBody());
        verify(servicio).listar("MIXTO", "ACTIVA", "2", "Ana", principal);
    }

    @Test
    void rechazaBusquedaRepetidaAntesDeConsultarElServicio() {
        ServicioTarjetasRfid1 servicio = mock(ServicioTarjetasRfid1.class);
        MockHttpServletRequest solicitud = new MockHttpServletRequest();
        solicitud.addParameter("busqueda", "a", "b");

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class, () ->
                new ControladorTarjetasRfid1(servicio).listar("MIXTO", "TODAS", "1", "a,b", solicitud, null));

        assertEquals(HttpStatus.BAD_REQUEST, error.estadoHttp());
        verifyNoInteractions(servicio);
    }
}
