package mx.smartparking.api.clientes.administracion.servicio;

import java.util.List;
import java.util.Optional;
import java.util.regex.Pattern;
import java.util.stream.Stream;
import mx.smartparking.api.clientes.administracion.modelo.ClienteResumenAdministracion;
import mx.smartparking.api.clientes.administracion.modelo.DetalleClienteAdministracion;
import mx.smartparking.api.clientes.administracion.modelo.DetalleMembresiaAdministracion;
import mx.smartparking.api.clientes.administracion.modelo.PaginaClientesAdministracion;
import mx.smartparking.api.clientes.administracion.modelo.PlanMembresiaAdministracion;
import mx.smartparking.api.clientes.configuracion.CatalogoMembresia;
import mx.smartparking.api.clientes.modelo.EstadoMembresia;
import mx.smartparking.api.clientes.administracion.persistencia.ClienteFilaPersistido;
import mx.smartparking.api.clientes.administracion.persistencia.DetalleClientePersistido;
import mx.smartparking.api.clientes.administracion.persistencia.RepositorioClientesAdministracion;
import mx.smartparking.api.clientes.administracion.persistencia.ResultadoPaginaClientes;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/** Consulta los clientes y sus membresías para mostrarlos al propietario o a un operador autorizado. */
@Service
public class ServicioAdministracionClientes {

    private static final int TAMANO_PAGINA = 10;
    private static final int MAXIMO_CARACTERES_BUSQUEDA = 100;
    private static final Pattern FORMATO_CODIGO_PUBLICO = Pattern.compile("CLI-[0-9]{4,}");
    private static final String ERROR_LISTA = "No pudimos cargar la lista de clientes. Inténtalo más tarde.";
    private static final String ERROR_DETALLE = "No pudimos cargar la información del cliente. Inténtalo más tarde.";

    private final RepositorioClientesAdministracion repositorio;
    private final ServicioEventosAdministracion eventos;
    private final CatalogoMembresia catalogo;
    private final TransactionTemplate transaccionLectura;

    @Autowired
    public ServicioAdministracionClientes(
            RepositorioClientesAdministracion repositorio,
            ServicioEventosAdministracion eventos,
            CatalogoMembresia catalogo,
            PlatformTransactionManager administradorTransacciones) {
        this.repositorio = repositorio;
        this.eventos = eventos;
        this.catalogo = catalogo;
        this.transaccionLectura = new TransactionTemplate(administradorTransacciones);
        this.transaccionLectura.setReadOnly(true);
        this.transaccionLectura.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
    }

    /** Consulta el total y la página con los mismos datos guardados para que las cifras coincidan. */
    public PaginaClientesAdministracion listar(
            String paginaSolicitada,
            String filtroSolicitado,
            PrincipalPropietario principal) {
        return listar(paginaSolicitada, filtroSolicitado, null, principal);
    }

    /** Lee una página del directorio combinando estado de membresía y texto de búsqueda. */
    public PaginaClientesAdministracion listar(
            String paginaSolicitada,
            String filtroSolicitado,
            String busquedaSolicitada,
            PrincipalPropietario principal) {
        exigirAccesoAdministrativo(principal);
        int pagina = validarPagina(paginaSolicitada);
        String filtro = validarFiltro(filtroSolicitado);
        String busqueda = validarBusqueda(busquedaSolicitada);
        String cursor = eventos.cursorActual();
        ResultadoPaginaClientes resultado = transaccionLectura.execute(estado ->
                repositorio.consultarPagina(pagina, TAMANO_PAGINA, filtro, busqueda));
        if (resultado == null) {
            throw servicioNoDisponible(ERROR_LISTA);
        }
        List<ClienteResumenAdministracion> items = resultado.items().stream()
                .map(this::resumen)
                .toList();
        return new PaginaClientesAdministracion(
                items,
                resultado.pagina(),
                TAMANO_PAGINA,
                resultado.totalClientes(),
                resultado.totalRegistros(),
                resultado.totalPaginas(),
                cursor);
    }

    /** Busca al cliente por su código público sin mostrar identificadores internos. */
    public DetalleClienteAdministracion consultarDetalle(
            String codigoPublico,
            PrincipalPropietario principal) {
        exigirAccesoAdministrativo(principal);
        validarCodigoPublico(codigoPublico);
        Optional<DetalleClientePersistido> resultado = transaccionLectura.execute(estado ->
                repositorio.consultarDetalle(codigoPublico));
        if (resultado == null) {
            throw servicioNoDisponible(ERROR_DETALLE);
        }
        DetalleClientePersistido detalle = resultado.orElseThrow(ServicioAdministracionClientes::clienteNoEncontrado);
        EstadoMembresia estado = estadoMembresia(detalle.estadoMembresia());
        DetalleMembresiaAdministracion membresia = estado == EstadoMembresia.SIN_MEMBRESIA
                ? null
                : detalleMembresia(detalle);
        return new DetalleClienteAdministracion(
                detalle.codigo(),
                nombreCompleto(detalle.nombres(), detalle.primerApellido(), detalle.segundoApellido()),
                estado,
                membresia);
    }

    private ClienteResumenAdministracion resumen(ClienteFilaPersistido cliente) {
        return new ClienteResumenAdministracion(
                cliente.codigo(),
                nombreCompleto(cliente.nombres(), cliente.primerApellido(), cliente.segundoApellido()),
                estadoMembresia(cliente.estadoMembresia()));
    }

    private DetalleMembresiaAdministracion detalleMembresia(DetalleClientePersistido detalle) {
        PlanMembresiaAdministracion plan = new PlanMembresiaAdministracion(
                catalogo.nombre(),
                catalogo.importeMenorUnidad(),
                catalogo.moneda(),
                catalogo.intervalo(),
                catalogo.intervaloCantidad());
        return new DetalleMembresiaAdministracion(
                plan,
                detalle.periodoInicio(),
                detalle.periodoFin(),
                detalle.siguienteCobroEn(),
                detalle.cancelacionAlFinal());
    }

    private static String nombreCompleto(String nombres, String primerApellido, String segundoApellido) {
        return Stream.of(nombres, primerApellido, segundoApellido)
                .filter(valor -> valor != null && !valor.isBlank())
                .map(String::strip)
                .collect(java.util.stream.Collectors.joining(" "));
    }

    private static int validarPagina(String texto) {
        try {
            int pagina = Integer.parseInt(texto);
            if (pagina < 1) {
                throw new NumberFormatException("La página debe ser positiva.");
            }
            return pagina;
        } catch (NumberFormatException excepcion) {
            throw new ErrorConfiguracion(
                    HttpStatus.BAD_REQUEST,
                    "No pudimos cargar esa parte de la lista. Actualízala e inténtalo de nuevo.",
                    "PAGINA_NO_VALIDA");
        }
    }

    private static String validarFiltro(String filtro) {
        if (filtro == null) {
            return "todos";
        }
        if (List.of("todos", "sin-membresia", "activa", "cancelada").contains(filtro)) {
            return filtro;
        }
        throw new ErrorConfiguracion(
                HttpStatus.BAD_REQUEST,
                "Elige un estado de membresía válido.",
                "FILTRO_MEMBRESIA_NO_VALIDO");
    }

    private static String validarBusqueda(String busqueda) {
        if (busqueda == null) {
            return null;
        }
        String normalizada = busqueda.strip().replaceAll("\\s+", " ");
        if (normalizada.isEmpty()) {
            return null;
        }
        if (normalizada.codePointCount(0, normalizada.length()) > MAXIMO_CARACTERES_BUSQUEDA) {
            throw new ErrorConfiguracion(
                    HttpStatus.BAD_REQUEST,
                    "La búsqueda no puede superar 100 caracteres.",
                    "BUSQUEDA_CLIENTE_NO_VALIDA");
        }
        return normalizada;
    }

    private static void validarCodigoPublico(String codigoPublico) {
        if (codigoPublico == null || !FORMATO_CODIGO_PUBLICO.matcher(codigoPublico).matches()) {
            throw new ErrorConfiguracion(
                    HttpStatus.BAD_REQUEST,
                    "El código del cliente no es válido.",
                    "CODIGO_CLIENTE_NO_VALIDO");
        }
    }

    private static EstadoMembresia estadoMembresia(String estado) {
        if (estado == null) {
            throw servicioNoDisponible(ERROR_DETALLE);
        }
        try {
            return EstadoMembresia.valueOf(estado);
        } catch (IllegalArgumentException excepcion) {
            throw servicioNoDisponible(ERROR_DETALLE);
        }
    }

    private static void exigirAccesoAdministrativo(PrincipalPropietario principal) {
        if (principal == null) {
            throw new ErrorConfiguracion(HttpStatus.UNAUTHORIZED, "Inicia sesión para ver esta información.",
                    "SESION_NO_VALIDA");
        }
        if (principal.rol() != RolCuenta.DUENO && principal.rol() != RolCuenta.OPERADOR) {
            throw new ErrorConfiguracion(HttpStatus.FORBIDDEN, "No tienes permiso para ver esta información.",
                    "PERMISO_NO_VALIDO");
        }
    }

    private static ErrorConfiguracion clienteNoEncontrado() {
        return new ErrorConfiguracion(HttpStatus.NOT_FOUND, "No encontramos a este cliente.",
                "CLIENTE_NO_ENCONTRADO");
    }

    private static ErrorConfiguracion servicioNoDisponible(String mensaje) {
        return new ErrorConfiguracion(HttpStatus.SERVICE_UNAVAILABLE, mensaje, "SERVICIO_NO_DISPONIBLE");
    }
}
