package mx.smartparking.api.historial.servicio;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.format.ResolverStyle;
import java.util.List;
import java.util.Locale;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.historial.controlador.RespuestaHistorialAccesos;
import mx.smartparking.api.historial.controlador.RespuestaHistorialAccesos.Item;
import mx.smartparking.api.historial.controlador.RespuestaHistorialAccesos.Persona;
import mx.smartparking.api.historial.persistencia.ConsultaHistorialAccesos;
import mx.smartparking.api.historial.persistencia.FilaHistorialAcceso;
import mx.smartparking.api.historial.persistencia.RepositorioHistorialAccesosJdbc;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/** Revisa los filtros y prepara las fechas del historial según la zona horaria del estacionamiento. */
@Service
public final class ServicioHistorialAccesos {

    private static final int TAMANO_PAGINA = 10;
    private static final String PERSONA_NO_DISPONIBLE = "Persona no disponible";
    private static final DateTimeFormatter FORMATO_LOCAL = DateTimeFormatter
            .ofPattern("uuuu-MM-dd'T'HH:mm:ssXXX", Locale.ROOT).withResolverStyle(ResolverStyle.STRICT);
    private final RepositorioHistorialAccesosJdbc repositorio;
    private final ServicioEventosAdministracion eventos;
    private final TransactionTemplate lectura;

    @Autowired
    public ServicioHistorialAccesos(
            RepositorioHistorialAccesosJdbc repositorio,
            ServicioEventosAdministracion eventos,
            PlatformTransactionManager administrador) {
        this.repositorio = repositorio;
        this.eventos = eventos;
        this.lectura = new TransactionTemplate(administrador);
        this.lectura.setReadOnly(true);
        this.lectura.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
    }

    /**
     * Prepara el seguimiento de cambios antes de consultar la página para no perder avisos durante la
     * lectura.
     */
    public RespuestaHistorialAccesos consultar(String paginaSolicitada, String lectorSolicitado,
            String resultadoSolicitado, String periodoSolicitado, String desdeSolicitado, String hastaSolicitado) {
        int pagina = validarPagina(paginaSolicitada);
        String lector = validarFiltro(lectorSolicitado, "TODOS", "TODOS", "RFID2", "RFID3", "MANUAL");
        String resultado = validarFiltro(resultadoSolicitado, "TODOS", "TODOS", "AUTORIZADA", "DENEGADA");
        String periodo = validarFiltro(periodoSolicitado, "ULTIMOS_7_DIAS", "ULTIMOS_7_DIAS",
                "HOY", "ULTIMOS_30_DIAS", "TODO", "PERSONALIZADO");
        String cursor = eventos.cursorActual();
        ConsultaHistorialAccesos consulta = lectura.execute(status -> {
            String zonaHoraria = repositorio.consultarZonaHoraria();
            RangoFechas rango = calcularRango(periodo, desdeSolicitado, hastaSolicitado, ZoneId.of(zonaHoraria));
            return repositorio.consultar(pagina, lector, resultado, zonaHoraria, rango.desde(), rango.hasta());
        });
        if (consulta == null) {
            throw error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                    "No pudimos cargar el historial. Inténtalo más tarde.");
        }
        ZoneId zona = ZoneId.of(consulta.zonaHoraria());
        List<Item> items = consulta.items().stream().map(fila -> mapear(fila, zona)).toList();
        return new RespuestaHistorialAccesos(items, pagina, TAMANO_PAGINA, consulta.totalRegistros(),
                consulta.haySiguiente(), consulta.zonaHoraria(), cursor);
    }

    private static RangoFechas calcularRango(String periodo, String desde, String hasta, ZoneId zona) {
        if ("PERSONALIZADO".equals(periodo)) {
            LocalDate fechaDesde = validarFecha(desde);
            LocalDate fechaHasta = validarFecha(hasta);
            if (fechaHasta.isBefore(fechaDesde)) {
                throw error(HttpStatus.BAD_REQUEST, "RANGO_NO_VALIDO",
                        "La fecha final debe ser igual o posterior a la fecha inicial.");
            }
            return new RangoFechas(fechaDesde.atStartOfDay(zona).toInstant(),
                    fechaHasta.plusDays(1).atStartOfDay(zona).toInstant());
        }
        LocalDate hoy = LocalDate.now(zona);
        return switch (periodo) {
            case "HOY" -> new RangoFechas(hoy.atStartOfDay(zona).toInstant(), hoy.plusDays(1).atStartOfDay(zona).toInstant());
            case "ULTIMOS_30_DIAS" -> new RangoFechas(hoy.minusDays(29).atStartOfDay(zona).toInstant(),
                    hoy.plusDays(1).atStartOfDay(zona).toInstant());
            case "TODO" -> new RangoFechas(null, null);
            default -> new RangoFechas(hoy.minusDays(6).atStartOfDay(zona).toInstant(),
                    hoy.plusDays(1).atStartOfDay(zona).toInstant());
        };
    }

    private static LocalDate validarFecha(String texto) {
        try {
            if (texto == null || !texto.matches("\\d{4}-\\d{2}-\\d{2}")) {
                throw new IllegalArgumentException();
            }
            return LocalDate.parse(texto, DateTimeFormatter.ISO_LOCAL_DATE.withResolverStyle(ResolverStyle.STRICT));
        } catch (RuntimeException excepcion) {
            throw error(HttpStatus.BAD_REQUEST, "FECHA_NO_VALIDA",
                    "Indica un rango de fechas válido para consultar el historial.");
        }
    }

    private record RangoFechas(Instant desde, Instant hasta) {
    }

    private static Item mapear(FilaHistorialAcceso fila, ZoneId zona) {
        Persona persona = fila.tipoPersona() == null ? null : new Persona(
                fila.tipoPersona(), fila.nombrePersona() == null || fila.nombrePersona().isBlank()
                        ? PERSONA_NO_DISPONIBLE : fila.nombrePersona());
        return new Item(fila.id(), fila.ocurridoEn().toString(), FORMATO_LOCAL.format(fila.ocurridoEn().atZone(zona)),
                fila.lector(), fila.resultado(), fila.motivo(), persona);
    }

    private static int validarPagina(String texto) {
        try {
            int pagina = Integer.parseInt(texto);
            if (pagina < 1) {
                throw new NumberFormatException();
            }
            return pagina;
        } catch (NumberFormatException excepcion) {
            throw error(HttpStatus.BAD_REQUEST, "PAGINA_NO_VALIDA", "La página debe ser un entero desde 1.");
        }
    }

    private static String validarFiltro(String valor, String predeterminado, String... permitidos) {
        String normalizado = valor == null ? predeterminado : valor;
        for (String permitido : permitidos) {
            if (permitido.equals(normalizado)) {
                return normalizado;
            }
        }
        throw error(HttpStatus.BAD_REQUEST, "FILTRO_NO_VALIDO", "El filtro del historial no es válido.");
    }

    private static ErrorConfiguracion error(HttpStatus estado, String codigo, String mensaje) {
        return new ErrorConfiguracion(estado, mensaje, codigo);
    }
}
