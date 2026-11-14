package mx.smartparking.api.operadores;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Locale;
import java.util.Optional;
import java.util.UUID;
import java.util.regex.Pattern;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;
import mx.smartparking.api.activacion.PreparacionInvitacionOperador;
import mx.smartparking.api.activacion.ServicioActivacionOperador;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.persistencia.RepositorioOperadores;
import mx.smartparking.api.persistencia.RepositorioOperadores.ComprobanteRegistroOperador;
import mx.smartparking.api.persistencia.RepositorioOperadores.ResultadoPaginaOperadores;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/** Registra operadores sin duplicar solicitudes repetidas y permite consultar su directorio. */
@Service
public class ServicioOperadores {

    private static final Logger LOG = LoggerFactory.getLogger(ServicioOperadores.class);
    private static final int TAMANO_PAGINA = 10;
    private static final int MAXIMO_NOMBRES = 120;
    private static final int MAXIMO_APELLIDOS = 80;
    private static final int MAXIMO_CORREO = 254;
    private static final Pattern FORMATO_CORREO = Pattern.compile("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$");

    private final RepositorioOperadores repositorio;
    private final ServicioActivacionOperador activacion;
    private final ServicioEventosAdministracion eventos;
    private final TransactionTemplate transaccion;
    private final TransactionTemplate transaccionLectura;

    @Autowired
    public ServicioOperadores(
            RepositorioOperadores repositorio,
            ServicioActivacionOperador activacion,
            ServicioEventosAdministracion eventos,
            PlatformTransactionManager administradorTransacciones) {
        this.repositorio = repositorio;
        this.activacion = activacion;
        this.eventos = eventos;
        this.transaccion = new TransactionTemplate(administradorTransacciones);
        this.transaccionLectura = new TransactionTemplate(administradorTransacciones);
        this.transaccionLectura.setReadOnly(true);
        this.transaccionLectura.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
    }

    /** Muestra hasta diez operadores por página junto con el estado de sus invitaciones. */
    public PaginaOperadores listar(String paginaSolicitada, PrincipalPropietario principal) {
        return listar(paginaSolicitada, null, "TODOS", principal);
    }

    /** Busca operadores por texto y estado antes de contar los resultados y dividirlos en páginas. */
    public PaginaOperadores listar(
            String paginaSolicitada,
            String busquedaSolicitada,
            String estadoSolicitado,
            PrincipalPropietario principal) {
        exigirDueno(principal);
        int pagina = validarPagina(paginaSolicitada);
        String busqueda = validarBusqueda(busquedaSolicitada);
        EstadoCuentaOperador estado = validarEstadoFiltro(estadoSolicitado).estadoCuenta();
        String cursor = eventos.cursorActual();
        ResultadoPaginaOperadores resultado = transaccionLectura.execute(status ->
                repositorio.consultarPagina(pagina, TAMANO_PAGINA, busqueda, estado));
        if (resultado == null) {
            throw error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                    "No pudimos cargar la lista de operadores. Inténtalo más tarde.");
        }
        return new PaginaOperadores(
                resultado.items(), resultado.pagina(), TAMANO_PAGINA,
                resultado.totalRegistros(), resultado.totalPaginas(), cursor);
    }

    /** Guarda una cuenta pendiente e intenta enviar la invitación después de confirmar el registro. */
    public RespuestaRegistroOperador registrar(
            SolicitudRegistroOperador solicitud, String claveIdempotencia, PrincipalPropietario principal) {
        exigirDueno(principal);
        DatosRegistroOperador datos = validarSolicitud(solicitud);
        String claveHash = hashClaveIdempotencia(claveIdempotencia);
        String huella = huella(datos);

        TransicionRegistro transicionRegistro = transaccion.execute(status -> {
            Optional<ComprobanteRegistroOperador> comprobante = repositorio.buscarComprobante(
                    principal.cuentaId(), claveHash);
            if (comprobante.isPresent()) {
                return reproducirRegistro(principal.cuentaId(), claveHash, huella);
            }
            throw error(HttpStatus.CONFLICT, "EMPLEADO_REQUERIDO",
                    "Registra un empleado y concédele acceso desde su ficha.");
        });
        if (transicionRegistro == null) {
            throw error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                    "No pudimos confirmar si se agregó el operador. Actualiza la lista antes de volver a intentarlo.");
        }
        if (!transicionRegistro.creado()) {
            return respuestaDeRegistroExistente(transicionRegistro.operadorId());
        }

        publicarActualizacion();
        String estadoInvitacion = enviarInvitacionInicial(transicionRegistro);
        return new RespuestaRegistroOperador(
                transicionRegistro.operadorId(), EstadoCuentaOperador.PENDIENTE, estadoInvitacion);
    }

    private TransicionRegistro reproducirRegistro(UUID duenoCuentaId, String claveHash, String huella) {
        ComprobanteRegistroOperador comprobante = repositorio.buscarComprobante(duenoCuentaId, claveHash)
                .orElseThrow(() -> error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                        "No pudimos agregar el operador. Inténtalo más tarde."));
        if (!hashesIguales(comprobante.huellaSolicitud(), huella)) {
            throw error(HttpStatus.CONFLICT, "CLAVE_IDEMPOTENCIA_REUTILIZADA",
                    "No se pudo agregar al operador con esos datos. Actualiza la lista e inténtalo de nuevo.");
        }
        if (!"COMPLETADA".equals(comprobante.estado()) || comprobante.operadorId() == null) {
            throw error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                    "No pudimos agregar el operador. Inténtalo más tarde.");
        }
        return new TransicionRegistro(comprobante.operadorId(), null, false);
    }

    private String enviarInvitacionInicial(TransicionRegistro transicionRegistro) {
        try {
            EstadoEnvioInvitacion resultado = activacion.enviarInicial(transicionRegistro.preparacion());
            if (resultado != null) {
                return resultado.name();
            }
        } catch (RuntimeException excepcion) {
            // La cuenta ya quedó registrada; si se repite la solicitud, se puede consultar la misma invitación.
        }
        return consultarEstadoInvitacion(transicionRegistro.operadorId());
    }

    private RespuestaRegistroOperador respuestaDeRegistroExistente(UUID operadorId) {
        Operador operador = repositorio.buscarPorId(operadorId).orElseThrow(() ->
                error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                        "No pudimos consultar esta cuenta. Inténtalo más tarde."));
        return new RespuestaRegistroOperador(operadorId, operador.estado(), operador.estadoInvitacion());
    }

    private String consultarEstadoInvitacion(UUID operadorId) {
        Optional<Operador> operador = repositorio.buscarPorId(operadorId);
        return operador.map(Operador::estadoInvitacion).orElseThrow(() ->
                error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                        "No pudimos consultar la invitación. Inténtalo más tarde."));
    }

    private void publicarActualizacion() {
        try {
            eventos.publicarDirectorioOperadorActualizado();
        } catch (RuntimeException excepcion) {
            LOG.warn("No se pudo publicar la actualización del directorio de operadores.");
        }
    }

    private static DatosRegistroOperador validarSolicitud(SolicitudRegistroOperador solicitud) {
        if (solicitud == null) {
            throw error(HttpStatus.BAD_REQUEST, "SOLICITUD_NO_VALIDA", "Completa los datos del operador.");
        }
        String nombres = validarTexto(solicitud.nombres(), "tu nombre", MAXIMO_NOMBRES, false);
        String primerApellido = validarTexto(
                solicitud.primerApellido(), "tu primer apellido", MAXIMO_APELLIDOS, false);
        String segundoApellido = validarTexto(
                solicitud.segundoApellido(), "el segundo apellido", MAXIMO_APELLIDOS, true);
        String correo = solicitud.correo() == null
                ? ""
                : solicitud.correo().trim().toLowerCase(Locale.ROOT);
        if (correo.length() > MAXIMO_CORREO || correo.indexOf('\0') >= 0
                || !FORMATO_CORREO.matcher(correo).matches()) {
            throw error(HttpStatus.BAD_REQUEST, "SOLICITUD_NO_VALIDA", "Ingresa un correo válido.");
        }
        return new DatosRegistroOperador(nombres, primerApellido, segundoApellido, correo);
    }

    private static String validarTexto(String valor, String campo, int maximo, boolean opcional) {
        if (valor == null || valor.isBlank()) {
            if (opcional) {
                return null;
            }
            throw error(HttpStatus.BAD_REQUEST, "SOLICITUD_NO_VALIDA", "Ingresa " + campo + ".");
        }
        String normalizado = valor.strip();
        if (normalizado.length() > maximo || normalizado.indexOf('\0') >= 0) {
            throw error(HttpStatus.BAD_REQUEST, "SOLICITUD_NO_VALIDA",
                    "Escribe un texto más corto para " + campo + ".");
        }
        return normalizado;
    }

    private static int validarPagina(String texto) {
        try {
            int pagina = Integer.parseInt(texto);
            if (pagina < 1) {
                throw new NumberFormatException("La página debe ser positiva.");
            }
            return pagina;
        } catch (NumberFormatException excepcion) {
            throw error(HttpStatus.BAD_REQUEST, "PAGINA_NO_VALIDA",
                    "No pudimos cargar esa parte de la lista. Actualízala e inténtalo de nuevo.");
        }
    }

    private static String validarBusqueda(String texto) {
        if (texto == null || texto.isBlank()) {
            return null;
        }
        String normalizado = texto.strip();
        if (normalizado.codePointCount(0, normalizado.length()) > MAXIMO_CORREO
                || normalizado.indexOf('\0') >= 0) {
            throw error(HttpStatus.BAD_REQUEST, "BUSQUEDA_NO_VALIDA", "Escribe una búsqueda más corta.");
        }
        return normalizado;
    }

    private static EstadoFiltroOperador validarEstadoFiltro(String texto) {
        String normalizado = texto == null || texto.isBlank() ? "TODOS" : texto.strip().toUpperCase(Locale.ROOT);
        try {
            return EstadoFiltroOperador.valueOf(normalizado);
        } catch (IllegalArgumentException excepcion) {
            throw error(HttpStatus.BAD_REQUEST, "ESTADO_NO_VALIDO", "Selecciona un estado válido.");
        }
    }

    private static String hashClaveIdempotencia(String clave) {
        if (clave == null || clave.strip().length() < 16 || clave.length() > 200
                || clave.codePoints().anyMatch(Character::isISOControl)) {
            throw error(HttpStatus.BAD_REQUEST, "CLAVE_IDEMPOTENCIA_NO_VALIDA",
                    "No pudimos agregar la cuenta. Actualiza la lista e inténtalo de nuevo.");
        }
        return sha256(clave.getBytes(StandardCharsets.UTF_8));
    }

    private static String huella(DatosRegistroOperador datos) {
        MessageDigest digest = nuevoDigest();
        agregarCampo(digest, datos.nombres());
        agregarCampo(digest, datos.primerApellido());
        agregarCampo(digest, datos.segundoApellido());
        agregarCampo(digest, datos.correo());
        return HexFormat.of().formatHex(digest.digest());
    }

    private static void agregarCampo(MessageDigest digest, String valor) {
        if (valor == null) {
            digest.update(ByteBuffer.allocate(Integer.BYTES).putInt(-1).array());
            return;
        }
        byte[] bytes = valor.getBytes(StandardCharsets.UTF_8);
        digest.update(ByteBuffer.allocate(Integer.BYTES).putInt(bytes.length).array());
        digest.update(bytes);
    }

    private static String sha256(byte[] valor) {
        return HexFormat.of().formatHex(nuevoDigest().digest(valor));
    }

    private static MessageDigest nuevoDigest() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException("No pudimos completar la acción en este momento.", excepcion);
        }
    }

    private static boolean hashesIguales(String primero, String segundo) {
        if (primero == null || segundo == null) {
            return false;
        }
        return MessageDigest.isEqual(
                primero.getBytes(StandardCharsets.US_ASCII), segundo.getBytes(StandardCharsets.US_ASCII));
    }

    private static void exigirDueno(PrincipalPropietario principal) {
        if (principal == null) {
            throw error(HttpStatus.UNAUTHORIZED, "SESION_NO_VIGENTE", "Tu acceso venció. Inicia sesión de nuevo.");
        }
        if (principal.rol() != RolCuenta.DUENO) {
            throw error(HttpStatus.FORBIDDEN, "PERMISO_INSUFICIENTE", "No tienes acceso para hacer este cambio.");
        }
    }

    private static ErrorConfiguracion error(HttpStatus estado, String codigo, String mensaje) {
        return new ErrorConfiguracion(estado, mensaje, codigo);
    }

    private record TransicionRegistro(
            UUID operadorId,
            PreparacionInvitacionOperador preparacion,
            boolean creado) {
    }
}
