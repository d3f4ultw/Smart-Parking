package mx.smartparking.api.eventos;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;

class PublicadorAccesoAdministracionTest {

    @Test
    void fallaPosteriorACommitNoPropagaNiDetieneLaDecision() {
        ServicioEventosAdministracion eventos = mock(ServicioEventosAdministracion.class);
        doThrow(new IllegalStateException("fallo sintetico"))
                .when(eventos).publicarAccesoHistorialActualizado();
        PublicadorAccesoAdministracion publicador = new PublicadorAccesoAdministracion(eventos);

        try {
            assertDoesNotThrow(publicador::publicar);
            verify(eventos, timeout(1_000)).publicarAccesoHistorialActualizado();
        } finally {
            publicador.detener();
        }
    }

    @Test
    void publicacionLentaNoBloqueaElLlamador() throws Exception {
        ServicioEventosAdministracion eventos = mock(ServicioEventosAdministracion.class);
        CountDownLatch iniciada = new CountDownLatch(1);
        CountDownLatch liberar = new CountDownLatch(1);
        doAnswer(invocacion -> {
            iniciada.countDown();
            liberar.await(2, TimeUnit.SECONDS);
            return null;
        }).when(eventos).publicarAccesoHistorialActualizado();
        PublicadorAccesoAdministracion publicador = new PublicadorAccesoAdministracion(eventos);
        var llamador = Executors.newSingleThreadExecutor();
        try {
            var publicacion = llamador.submit(publicador::publicar);
            publicacion.get(1, TimeUnit.SECONDS);
            assertTrue(iniciada.await(1, TimeUnit.SECONDS));
        } finally {
            liberar.countDown();
            publicador.detener();
            llamador.shutdownNow();
        }
    }
}
