package mx.smartparking.ownerconsole.controlador;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;
import java.util.function.Supplier;
import javafx.application.Platform;

/** realiza las tareas sin detener la ventana y entrega sus resultados para actualizar la interfaz. */
public final class EjecutorJavaFx implements AutoCloseable {

    private final ExecutorService ejecutores = Executors.newFixedThreadPool(3, tarea -> {
        Thread hilo = new Thread(tarea, "smartparking-api");
        hilo.setDaemon(true);
        return hilo;
    });

    /**
     * realiza la tarea sin detener la ventana
     * entrega el resultado o el error para que la pantalla pueda actualizarse
     */
    public <T> void ejecutar(Supplier<T> tarea, Consumer<T> alCompletar, Consumer<Throwable> alFallar) {
        CompletableFuture.supplyAsync(tarea, ejecutores).whenComplete((resultado, error) ->
                Platform.runLater(() -> {
                    if (error == null) {
                        alCompletar.accept(resultado);
                    } else {
                        Throwable causa = error instanceof java.util.concurrent.CompletionException
                                && error.getCause() != null ? error.getCause() : error;
                        alFallar.accept(causa);
                    }
                }));
    }

    /**
     * pide detener las tareas que siguen en curso y evita que se inicien otras
     * continúa sin esperar a que esas tareas terminen
     */
    @Override
    public void close() {
        ejecutores.shutdownNow();
    }
}
