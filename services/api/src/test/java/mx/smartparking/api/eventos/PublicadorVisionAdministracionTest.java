package mx.smartparking.api.eventos;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class PublicadorVisionAdministracionTest {
    @Test
    void agrupaRafagaYConservaSenalRecibidaDuranteElEnvioInclusoSiFalla() {
        ScheduledExecutorService ejecutor = mock(ScheduledExecutorService.class);
        AtomicInteger publicaciones = new AtomicInteger();
        AtomicReference<PublicadorVisionAdministracion> referencia = new AtomicReference<>();
        PublicadorVisionAdministracion publicador = new PublicadorVisionAdministracion(() -> {
            if (publicaciones.incrementAndGet() == 1) {
                referencia.get().solicitar();
                throw new IllegalStateException("fallo sintético");
            }
        }, ejecutor);
        referencia.set(publicador);
        for (int i = 0; i < 100; i++) publicador.solicitar();
        ArgumentCaptor<Runnable> tareas = ArgumentCaptor.forClass(Runnable.class);
        verify(ejecutor).schedule(tareas.capture(), eq(1_000L), eq(TimeUnit.MILLISECONDS));
        tareas.getValue().run();
        verify(ejecutor, times(2)).schedule(tareas.capture(), eq(1_000L), eq(TimeUnit.MILLISECONDS));
        tareas.getAllValues().getLast().run();
        assertEquals(2, publicaciones.get());
        publicador.detener();
        publicador.solicitar();
        verify(ejecutor, times(2)).schedule(any(Runnable.class), eq(1_000L), eq(TimeUnit.MILLISECONDS));
        verify(ejecutor).shutdownNow();
    }
}
