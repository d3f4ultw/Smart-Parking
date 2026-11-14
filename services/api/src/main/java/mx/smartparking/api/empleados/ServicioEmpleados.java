package mx.smartparking.api.empleados;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.regex.Pattern;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.empleados.coordinacion.PuertoAdministracionEmpleadoOperador;
import mx.smartparking.api.empleados.coordinacion.ResultadoAccionEmpleadoOperador;
import mx.smartparking.api.empleados.coordinacion.ResultadoCambioCorreoEmpleadoOperador;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.persistencia.RepositorioEmpleados;
import mx.smartparking.api.persistencia.RepositorioEmpleados.ComprobanteRegistroEmpleado;
import mx.smartparking.api.persistencia.RepositorioEmpleados.ResultadoPaginaEmpleados;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/** Revisa y guarda los cambios de empleados y avisa a las pantallas cuando ya quedaron confirmados. */
@Service
public class ServicioEmpleados {

    private static final Logger LOG = LoggerFactory.getLogger(ServicioEmpleados.class);
    private static final int TAMANO_PAGINA = 10;
    private static final int MAXIMO_CARACTERES = 100;
    private static final int MAXIMO_CORREO = 254;
    private static final int MAXIMO_BUSQUEDA = 120;
    private static final Pattern FORMATO_CORREO = Pattern.compile("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$");
    private final RepositorioEmpleados repositorio;
    private final ServicioEventosAdministracion eventos;
    private final TransactionTemplate transaccion;
    private final TransactionTemplate transaccionLectura;
    private final PuertoAdministracionEmpleadoOperador accionesOperador;

    @Autowired
    public ServicioEmpleados(
            RepositorioEmpleados repositorio,
            ServicioEventosAdministracion eventos,
            PlatformTransactionManager administradorTransacciones,
            PuertoAdministracionEmpleadoOperador accionesOperador) {
        this.repositorio = repositorio;
        this.eventos = eventos;
        this.transaccion = new TransactionTemplate(administradorTransacciones);
        this.transaccionLectura = new TransactionTemplate(administradorTransacciones);
        this.transaccionLectura.setReadOnly(true);
        this.transaccionLectura.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
        this.accionesOperador = accionesOperador;
    }

    /** Permite preparar el servicio cuando solo se necesita el directorio de empleados. */
    ServicioEmpleados(
            RepositorioEmpleados repositorio,
            ServicioEventosAdministracion eventos,
            PlatformTransactionManager administradorTransacciones) {
        this(repositorio, eventos, administradorTransacciones, null);
    }

    /** Consulta una página con datos coherentes y prepara el aviso de cambios ocurridos durante la consulta. */
    public PaginaEmpleados listar(String paginaSolicitada) {
        return listar(paginaSolicitada, null, false);
    }

    /** Busca dentro del conjunto de empleados activos que aún no tienen una cuenta vinculada. */
    public PaginaEmpleados listar(
            String paginaSolicitada, String busquedaSolicitada, boolean soloElegiblesOperador) {
        int pagina = validarPagina(paginaSolicitada);
        String busqueda = validarBusqueda(busquedaSolicitada);
        if (!soloElegiblesOperador && busqueda != null) {
            throw error(HttpStatus.BAD_REQUEST, "BUSQUEDA_NO_VALIDA", "La búsqueda solicitada no es válida.");
        }
        String cursor = eventos.cursorActual();
        ResultadoPaginaEmpleados resultado = transaccionLectura.execute(status ->
                soloElegiblesOperador
                        ? repositorio.consultarElegiblesParaOperador(pagina, TAMANO_PAGINA, busqueda)
                        : repositorio.consultarPagina(pagina, TAMANO_PAGINA));
        if (resultado == null) {
            throw error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                    "No pudimos cargar la lista. Inténtalo más tarde.");
        }
        return new PaginaEmpleados(
                List.copyOf(resultado.items()),
                resultado.pagina(),
                TAMANO_PAGINA,
                resultado.totalRegistros(),
                resultado.totalPaginas(),
                cursor);
    }

    /** Busca la información de un empleado conservando su número completo. */
    public Empleado consultar(String idTexto) {
        long id = validarId(idTexto);
        Empleado empleado = transaccionLectura.execute(status -> repositorio.obtener(id).orElse(null));
        if (empleado == null) {
            throw error(HttpStatus.NOT_FOUND, "EMPLEADO_NO_ENCONTRADO", "No encontramos a este empleado.");
        }
        return empleado;
    }

    /** Registra un empleado, con correo opcional, y devuelve el mismo resultado si se repite la solicitud. */
    public RespuestaRegistroEmpleado registrar(
            SolicitudRegistroEmpleado solicitud,
            String claveIdempotencia,
            PrincipalPropietario propietario) {
        DatosRegistro datos = validarSolicitud(solicitud);
        String claveHash = hashClaveIdempotencia(claveIdempotencia);
        String huella = huella(datos);
        TransicionRegistro transicionRegistro = transaccion.execute(status -> {
            boolean reservaCreada = repositorio.reservarRegistro(propietario.cuentaId(), claveHash, huella);
            if (!reservaCreada) {
                return reproducirRegistro(propietario.cuentaId(), claveHash, huella);
            }
            long empleadoId = repositorio.crearEmpleado(
                    datos.nombres(), datos.primerApellido(), datos.segundoApellido(),
                    datos.correo(), datos.correoNormalizado());
            repositorio.completarRegistro(propietario.cuentaId(), claveHash, empleadoId);
            return new TransicionRegistro(new RespuestaRegistroEmpleado(
                    empleadoId, Empleado.codigoDe(empleadoId)), true);
        });
        if (transicionRegistro == null) {
            throw error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                    "No pudimos agregar al empleado. Inténtalo más tarde.");
        }
        if (transicionRegistro.publicarEvento()) {
            publicarActualizacion();
        }
        return transicionRegistro.respuesta();
    }

    /** Activa o desactiva al empleado y actualiza también su cuenta de operador cuando está vinculada. */
    public Empleado cambiarEstado(
            String idTexto, String estadoTexto, String ifMatch, PrincipalPropietario propietario) {
        validarId(idTexto);
        if (accionesOperador != null) {
            accionesOperador.cambiarEstadoEmpleado(idTexto, estadoTexto, ifMatch, propietario);
            return consultar(idTexto);
        }
        return cambiarEstadoSoloEmpleado(idTexto, estadoTexto, ifMatch);
    }

    /** Permite cambiar el estado cuando se utiliza únicamente el directorio de empleados. */
    public Empleado cambiarEstado(String idTexto, String estadoTexto, String ifMatch) {
        return cambiarEstadoSoloEmpleado(idTexto, estadoTexto, ifMatch);
    }

    public ResultadoAccionEmpleadoOperador promocionar(
            String idTexto, String ifMatch, String claveIdempotencia, PrincipalPropietario propietario) {
        validarId(idTexto);
        return exigirAccionesOperador().promocionar(idTexto, ifMatch, claveIdempotencia, propietario);
    }

    public ResultadoAccionEmpleadoOperador promocionar(
            String idTexto,
            String correo,
            String ifMatch,
            String claveIdempotencia,
            PrincipalPropietario propietario) {
        validarId(idTexto);
        return exigirAccionesOperador().promocionar(
                idTexto, correo, ifMatch, claveIdempotencia, propietario);
    }

    public ResultadoCambioCorreoEmpleadoOperador cambiarCorreo(
            String idTexto,
            String correo,
            String ifMatch,
            String claveIdempotencia,
            PrincipalPropietario propietario) {
        validarId(idTexto);
        return exigirAccionesOperador().cambiarCorreo(
                idTexto, correo, ifMatch, claveIdempotencia, propietario);
    }

    public ResultadoAccionEmpleadoOperador desactivarAcceso(
            String idTexto, String ifMatch, String claveIdempotencia, PrincipalPropietario propietario) {
        validarId(idTexto);
        return exigirAccionesOperador().desactivarAcceso(idTexto, ifMatch, claveIdempotencia, propietario);
    }

    public ResultadoAccionEmpleadoOperador vincular(
            String idTexto,
            UUID operadorId,
            String revisionOperador,
            boolean copiarCorreoOperador,
            String ifMatch,
            String claveIdempotencia,
            PrincipalPropietario propietario) {
        validarId(idTexto);
        return exigirAccionesOperador().vincular(
                idTexto, operadorId, revisionOperador, copiarCorreoOperador, ifMatch, claveIdempotencia, propietario);
    }

    private Empleado cambiarEstadoSoloEmpleado(String idTexto, String estadoTexto, String ifMatch) {
        long id = validarId(idTexto);
        long revisionEsperada = validarRevision(ifMatch);
        EstadoEmpleado estadoDeseado = validarEstado(estadoTexto);
        TransicionEstado cambio = transaccion.execute(status -> {
            Empleado actual = repositorio.bloquearPorId(id).orElseThrow(() -> error(
                    HttpStatus.NOT_FOUND, "EMPLEADO_NO_ENCONTRADO", "No encontramos a este empleado."));
            if (actual.revision() != revisionEsperada) {
                throw error(HttpStatus.PRECONDITION_FAILED, "REVISION_OBSOLETA",
                        "La información cambió. Actualiza la lista antes de continuar.");
            }
            if (actual.estado() == estadoDeseado) {
                return new TransicionEstado(actual, false);
            }
            if (actual.revision() == Long.MAX_VALUE) {
                throw error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                        "No pudimos cargar la lista. Inténtalo más tarde.");
            }
            Empleado actualizado = repositorio.actualizarEstado(id, estadoDeseado, actual.revision() + 1);
            return new TransicionEstado(actualizado, true);
        });
        if (cambio == null) {
            throw error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                    "No pudimos cargar la lista. Inténtalo más tarde.");
        }
        if (cambio.publicarEvento()) {
            publicarActualizacion();
        }
        return cambio.empleado();
    }

    private PuertoAdministracionEmpleadoOperador exigirAccionesOperador() {
        if (accionesOperador == null) {
            throw error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                    "No pudimos completar el cambio. Inténtalo más tarde.");
        }
        return accionesOperador;
    }

    private TransicionRegistro reproducirRegistro(UUID cuentaId, String claveHash, String huella) {
        ComprobanteRegistroEmpleado comprobante = repositorio.buscarComprobante(cuentaId, claveHash)
                .orElseThrow(() -> error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                    "No pudimos agregar al empleado. Inténtalo más tarde."));
        if (!hashesIguales(comprobante.huellaSolicitud(), huella)) {
            throw error(HttpStatus.CONFLICT, "CLAVE_IDEMPOTENCIA_REUTILIZADA",
                    "No se pudo agregar al empleado con esos datos. Actualiza la lista e inténtalo de nuevo.");
        }
        if (!"COMPLETADA".equals(comprobante.estado()) || comprobante.empleadoId() == null) {
            throw error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                    "No pudimos agregar al empleado. Inténtalo más tarde.");
        }
        long empleadoId = comprobante.empleadoId();
        return new TransicionRegistro(new RespuestaRegistroEmpleado(
                empleadoId, Empleado.codigoDe(empleadoId)), false);
    }

    private void publicarActualizacion() {
        try {
            eventos.publicarDirectorioActualizado();
        } catch (RuntimeException excepcion) {
            LOG.warn("No se pudo publicar la actualización del directorio administrativo.");
        }
    }

    private static DatosRegistro validarSolicitud(SolicitudRegistroEmpleado solicitud) {
        if (solicitud == null) {
            throw error(HttpStatus.BAD_REQUEST, "SOLICITUD_NO_VALIDA", "Completa los datos del empleado.");
        }
        String nombres = validarNombre(solicitud.nombres(), "tu nombre", false);
        String primerApellido = validarNombre(solicitud.primerApellido(), "tu primer apellido", false);
        String segundoApellido = validarNombre(solicitud.segundoApellido(), "el segundo apellido", true);
        DatosCorreo correo = validarCorreoOpcional(solicitud.correo());
        return new DatosRegistro(nombres, primerApellido, segundoApellido, correo.correo(), correo.normalizado());
    }

    private static String validarNombre(String valor, String campo, boolean opcional) {
        String normalizado = valor == null ? "" : valor.strip();
        if (opcional && normalizado.isEmpty()) {
            return null;
        }
        if (normalizado.isEmpty()) {
            throw error(HttpStatus.BAD_REQUEST, "SOLICITUD_NO_VALIDA",
                    "Escribe " + campo + ".");
        }
        if (normalizado.indexOf('\0') >= 0) {
            throw error(HttpStatus.BAD_REQUEST, "SOLICITUD_NO_VALIDA", "Revisa este dato e inténtalo de nuevo.");
        }
        if (normalizado.codePointCount(0, normalizado.length()) > MAXIMO_CARACTERES) {
            throw error(HttpStatus.BAD_REQUEST, "SOLICITUD_NO_VALIDA",
                    "Escribe un texto más corto para " + campo + ".");
        }
        return normalizado;
    }

    private static DatosCorreo validarCorreoOpcional(String valor) {
        if (valor == null || valor.trim().isEmpty()) {
            return new DatosCorreo(null, null);
        }
        String correo = valor.trim();
        String normalizado = correo.toLowerCase(Locale.ROOT);
        if (normalizado.length() > MAXIMO_CORREO
                || normalizado.indexOf('\0') >= 0
                || !FORMATO_CORREO.matcher(normalizado).matches()) {
            throw error(HttpStatus.BAD_REQUEST, "SOLICITUD_NO_VALIDA", "Ingresa un correo válido.");
        }
        return new DatosCorreo(correo, normalizado);
    }

    private static int validarPagina(String texto) {
        try {
            int pagina = Integer.parseInt(texto);
            if (pagina < 1) {
                throw new NumberFormatException("La página debe ser positiva.");
            }
            return pagina;
        } catch (NumberFormatException excepcion) {
            throw error(HttpStatus.BAD_REQUEST, "PAGINA_NO_VALIDA", "No pudimos cargar esa parte de la lista. Actualízala e inténtalo de nuevo.");
        }
    }

    private static String validarBusqueda(String busqueda) {
        if (busqueda == null) {
            return null;
        }
        String valor = busqueda.trim();
        if (valor.isEmpty()) {
            return null;
        }
        if (valor.length() > MAXIMO_BUSQUEDA || valor.indexOf('\0') >= 0) {
            throw error(HttpStatus.BAD_REQUEST, "BUSQUEDA_NO_VALIDA", "La búsqueda solicitada no es válida.");
        }
        return valor;
    }

    private static long validarId(String texto) {
        try {
            long id = Long.parseLong(texto);
            if (id < 1) {
                throw new NumberFormatException("El identificador debe ser positivo.");
            }
            return id;
        } catch (NumberFormatException excepcion) {
            throw error(HttpStatus.BAD_REQUEST, "SOLICITUD_NO_VALIDA", "No encontramos a este empleado.");
        }
    }

    private static EstadoEmpleado validarEstado(String texto) {
        try {
            return EstadoEmpleado.valueOf(texto);
        } catch (RuntimeException excepcion) {
            throw error(HttpStatus.BAD_REQUEST, "ESTADO_NO_VALIDO", "Elige si el empleado estará activo o inactivo.");
        }
    }

    private static long validarRevision(String ifMatch) {
        if (ifMatch == null || ifMatch.length() < 3 || ifMatch.charAt(0) != '"'
                || ifMatch.charAt(ifMatch.length() - 1) != '"') {
            throw error(HttpStatus.BAD_REQUEST, "REVISION_NO_VALIDA", "La información cambió. Actualiza la lista antes de continuar.");
        }
        try {
            long revision = Long.parseLong(ifMatch.substring(1, ifMatch.length() - 1));
            if (revision < 1) {
                throw new NumberFormatException("La revisión debe ser positiva.");
            }
            return revision;
        } catch (NumberFormatException excepcion) {
            throw error(HttpStatus.BAD_REQUEST, "REVISION_NO_VALIDA", "La información cambió. Actualiza la lista antes de continuar.");
        }
    }

    private static String hashClaveIdempotencia(String clave) {
        if (clave == null || clave.strip().length() < 16 || clave.length() > 200
                || clave.codePoints().anyMatch(Character::isISOControl)) {
            throw error(HttpStatus.BAD_REQUEST, "CLAVE_IDEMPOTENCIA_NO_VALIDA",
                    "No pudimos completar el cambio. Actualiza la lista e inténtalo de nuevo.");
        }
        return sha256(clave.getBytes(StandardCharsets.UTF_8));
    }

    private static String huella(DatosRegistro datos) {
        MessageDigest digest = nuevoDigest();
        if (datos.correoNormalizado() != null) {
            agregarCampo(digest, "EMPLEADO_CORREO_V2");
        }
        agregarCampo(digest, datos.nombres());
        agregarCampo(digest, datos.primerApellido());
        agregarCampo(digest, datos.segundoApellido());
        if (datos.correoNormalizado() != null) {
            agregarCampo(digest, datos.correoNormalizado());
        }
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

    private static ErrorConfiguracion error(HttpStatus estado, String codigo, String mensaje) {
        return new ErrorConfiguracion(estado, mensaje, codigo);
    }

    private record DatosRegistro(
            String nombres, String primerApellido, String segundoApellido, String correo, String correoNormalizado) {
    }

    private record DatosCorreo(String correo, String normalizado) {
    }

    private record TransicionRegistro(RespuestaRegistroEmpleado respuesta, boolean publicarEvento) {
    }

    private record TransicionEstado(Empleado empleado, boolean publicarEvento) {
    }
}
