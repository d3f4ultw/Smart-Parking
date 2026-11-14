package mx.smartparking.api.eventos;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/** Recuerda los avisos recientes para que las pantallas puedan reconocer cuáles necesitan consultar. */
final class RegistroEventosAdministracion {

    static final String NOMBRE_EVENTO_EMPLEADOS = "empleado.directorio.actualizado";
    static final String NOMBRE_EVENTO_OPERADORES = "operador.directorio.actualizado";
    static final String NOMBRE_EVENTO_CLIENTE_REGISTRADO = "cliente.registrado";
    static final String NOMBRE_EVENTO_MEMBRESIA_ACTUALIZADA = "membresia.actualizada";
    static final String NOMBRE_EVENTO_CAPTURA_RFID1_ACTUALIZADA = "rfid1.captura.actualizada";
    static final String NOMBRE_EVENTO_TARJETAS_RFID1_ACTUALIZADAS = "rfid1.tarjetas.actualizadas";
    static final String NOMBRE_EVENTO_ACCESO_HISTORIAL_ACTUALIZADO = "acceso.historial.actualizado";
    static final String NOMBRE_EVENTO_VISION_ACTUALIZADA = "vision.ocupacion.actualizada";
    static final String NOMBRE_EVENTO_RESINCRONIZAR = "administracion.directorio.resincronizar";
    static final int CAPACIDAD_HISTORIAL = 256;
    private static final int LONGITUD_MAXIMA_CURSOR = 64;

    private final UUID epoca;
    private final ArrayDeque<Evento> historial = new ArrayDeque<>(CAPACIDAD_HISTORIAL);
    private long secuencia;

    RegistroEventosAdministracion() {
        this(UUID.randomUUID());
    }

    RegistroEventosAdministracion(UUID epoca) {
        this.epoca = epoca;
    }

    synchronized String cursorActual() {
        return cursor(secuencia);
    }

    synchronized Evento registrarCambio() {
        return registrarCambio(NOMBRE_EVENTO_EMPLEADOS);
    }

    synchronized Evento registrarCambio(String nombreEvento) {
        if (secuencia == Long.MAX_VALUE) {
            throw new IllegalStateException("No pudimos completar la acción en este momento.");
        }

        Evento evento = evento(++secuencia, nombreEvento);
        historial.addLast(evento);
        while (historial.size() > CAPACIDAD_HISTORIAL) {
            historial.removeFirst();
        }
        return evento;
    }

    synchronized Evento invalidacionActual() {
        return evento(secuencia, NOMBRE_EVENTO_RESINCRONIZAR);
    }

    synchronized PlanReproduccion resolver(String cursorSolicitado) {
        Cursor cursor = parsear(cursorSolicitado);
        if (cursor == null || !epoca.equals(cursor.epoca()) || cursor.secuencia() > secuencia) {
            return PlanReproduccion.resincronizar(cursorActual(), secuencia);
        }

        long primeraSecuencia = historial.isEmpty()
                ? secuencia + 1
                : historial.getFirst().secuencia();
        if (cursor.secuencia() < primeraSecuencia - 1) {
            return PlanReproduccion.resincronizar(cursorActual(), secuencia);
        }

        List<Evento> posteriores = new ArrayList<>();
        for (Evento evento : historial) {
            if (evento.secuencia() > cursor.secuencia()) {
                posteriores.add(evento);
            }
        }
        return PlanReproduccion.reproducir(cursor.secuencia(), cursorActual(), posteriores, secuencia);
    }

    private Cursor parsear(String valor) {
        if (valor == null || valor.isBlank() || valor.length() > LONGITUD_MAXIMA_CURSOR) {
            return null;
        }

        int separador = valor.indexOf(':');
        if (separador != 36 || valor.indexOf(':', separador + 1) >= 0) {
            return null;
        }

        try {
            UUID epocaCursor = UUID.fromString(valor.substring(0, separador));
            if (!epocaCursor.toString().equalsIgnoreCase(valor.substring(0, separador))) {
                return null;
            }
            long secuenciaCursor = Long.parseLong(valor.substring(separador + 1));
            return secuenciaCursor < 0 ? null : new Cursor(epocaCursor, secuenciaCursor);
        } catch (IllegalArgumentException excepcion) {
            return null;
        }
    }

    private Evento evento(long numero, String nombreEvento) {
        return new Evento(numero, cursor(numero), nombreEvento);
    }

    private String cursor(long numero) {
        return epoca + ":" + numero;
    }

    record Evento(long secuencia, String cursor, String nombreEvento) {
    }

    record PlanReproduccion(
            boolean requiereResincronizacion,
            long ultimaSecuenciaInicial,
            String cursorActual,
            List<Evento> eventos,
            long secuenciaActual) {

        static PlanReproduccion resincronizar(String cursorActual, long secuenciaActual) {
            return new PlanReproduccion(true, secuenciaActual - 1, cursorActual, List.of(), secuenciaActual);
        }

        static PlanReproduccion reproducir(
                long ultimaSecuenciaInicial, String cursorActual, List<Evento> eventos, long secuenciaActual) {
            return new PlanReproduccion(
                    false, ultimaSecuenciaInicial, cursorActual, List.copyOf(eventos), secuenciaActual);
        }
    }

    private record Cursor(UUID epoca, long secuencia) {
    }
}
