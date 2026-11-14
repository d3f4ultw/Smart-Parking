package mx.smartparking.api.accesos;

import java.time.DateTimeException;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.format.ResolverStyle;
import java.util.List;
import java.util.Locale;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/** Reúne la capacidad y las visitas actuales para que las pantallas puedan actualizarse cuando haya cambios. */
@Service
public final class ServicioAccesos {
    private static final int TAMANO_PAGINA = 10;
    private static final DateTimeFormatter FORMATO_LOCAL = DateTimeFormatter
            .ofPattern("uuuu-MM-dd'T'HH:mm:ssXXX", Locale.ROOT).withResolverStyle(ResolverStyle.STRICT);

    private final RepositorioAccesosJdbc repositorio;
    private final ServicioEventosAdministracion eventos;
    private final TransactionTemplate lectura;

    public ServicioAccesos(RepositorioAccesosJdbc repositorio, ServicioEventosAdministracion eventos,
            PlatformTransactionManager administrador) {
        this.repositorio = repositorio;
        this.eventos = eventos;
        this.lectura = new TransactionTemplate(administrador);
        this.lectura.setReadOnly(true);
        this.lectura.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
    }

    /**
     * Muestra el total de lugares, los ocupados y los disponibles, junto con una referencia
     * que ayuda a la pantalla a identificar cambios posteriores.
     */
    public RespuestaCapacidad capacidad() {
        String cursor = eventos.cursorActual();
        RepositorioAccesosJdbc.Capacidad capacidad = lectura.execute(estado -> repositorio.consultarCapacidad());
        if (capacidad == null) {
            throw noDisponible();
        }
        return new RespuestaCapacidad(capacidad.total(), capacidad.dentro(),
                Math.max(0L, capacidad.total() - capacidad.dentro()), cursor);
    }

    /**
     * Muestra una página de personas que siguen dentro del estacionamiento y una referencia
     * que ayuda a la pantalla a identificar cambios posteriores.
     */
    public RespuestaDentro dentro(String paginaSolicitada, String busquedaSolicitada) {
        int pagina = validarPagina(paginaSolicitada);
        String busqueda = validarBusqueda(busquedaSolicitada);
        String cursor = eventos.cursorActual();
        LecturaDentro resultado = lectura.execute(estado -> {
            String zona = repositorio.consultarZonaHoraria();
            return new LecturaDentro(zona, repositorio.consultarDentro(pagina, busqueda));
        });
        if (resultado == null) {
            throw noDisponible();
        }
        ZoneId zona;
        try {
            zona = ZoneId.of(resultado.zona());
        } catch (DateTimeException excepcion) {
            throw noDisponible();
        }
        List<RespuestaDentro.Item> items = resultado.pagina().items().stream()
                .map(visita -> new RespuestaDentro.Item(Long.toString(visita.id()),
                        new RespuestaDentro.Persona(visita.tipoPersona(), nombre(visita.nombrePersona()),
                                visita.codigoPersona()),
                        visita.estadoTarjeta(), visita.entrada().toString(),
                        FORMATO_LOCAL.format(visita.entrada().atZone(zona)),
                        visita.operacionId() == null ? null : new RespuestaDentro.SalidaManual(
                                visita.operacionId().toString(), visita.estadoManual())))
                .toList();
        return new RespuestaDentro(items, pagina, TAMANO_PAGINA, resultado.pagina().total(),
                resultado.pagina().haySiguiente(), resultado.zona(), cursor);
    }

    private static int validarPagina(String texto) {
        try {
            if (texto == null || !texto.matches("[1-9][0-9]*")) {
                throw new NumberFormatException();
            }
            return Integer.parseInt(texto);
        } catch (NumberFormatException excepcion) {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST,
                    "La página debe ser un entero desde 1.", "PAGINA_NO_VALIDA");
        }
    }

    private static String validarBusqueda(String texto) {
        if (texto != null && texto.codePoints().anyMatch(Character::isISOControl)) {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST,
                    "La búsqueda solicitada no es válida.", "BUSQUEDA_NO_VALIDA");
        }
        String valor = texto == null ? "" : texto.strip();
        if (valor.length() > 100) {
            throw new ErrorConfiguracion(HttpStatus.BAD_REQUEST,
                    "La búsqueda solicitada no es válida.", "BUSQUEDA_NO_VALIDA");
        }
        return valor;
    }

    private static String nombre(String valor) {
        return valor == null || valor.isBlank() ? "Persona no disponible" : valor;
    }

    private static ErrorConfiguracion noDisponible() {
        return new ErrorConfiguracion(HttpStatus.SERVICE_UNAVAILABLE,
                "No pudimos cargar los accesos en este momento.", "SERVICIO_NO_DISPONIBLE");
    }

    private record LecturaDentro(String zona, RepositorioAccesosJdbc.Pagina pagina) { }

    public record RespuestaCapacidad(
            long capacidadTotal, long vehiculosDentro, long capacidadDisponible, String cursorEventos) { }

    public record RespuestaDentro(
            List<Item> items, int pagina, int tamano, long totalRegistros, boolean haySiguiente,
            String zonaHoraria, String cursorEventos) {
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.ALWAYS)
        public record Item(
                String movimientoId, Persona persona, String estadoTarjeta, String entradaEn, String entradaEnLocal,
                SalidaManual salidaManual) { }
        public record Persona(String tipo, String nombre, String codigo) { }
        public record SalidaManual(String operacionId, String estado) { }
    }
}

