package mx.smartparking.api.rfid1.servicio;

import java.time.Clock;
import java.util.List;
import java.util.Optional;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.TipoEstacionamiento;
import mx.smartparking.api.eventos.PublicadorTarjetasRfid1;
import mx.smartparking.api.rfid1.PoliticaModalidadRfid1;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.CandidatoPersona;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.Cancelacion;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.Modalidad;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.Pagina;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.Tarjeta;
import mx.smartparking.api.rfid1.persistencia.RepositorioTarjetasRfid;
import mx.smartparking.api.rfid1.persistencia.RepositorioTarjetasRfid.ResultadoCancelacionTarjetaRfid1;
import mx.smartparking.api.persistencia.ConfiguracionPersistida;
import mx.smartparking.api.persistencia.RepositorioConfiguracion;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/** Comprueba los permisos y prepara por páginas la información privada de las tarjetas. */
@Service
public class ServicioTarjetasRfid1 {

    private static final int TAMANO_PAGINA = 10;
    private static final int MAXIMO_CANDIDATOS = 10;
    private static final List<String> TIPOS = List.of("CLIENTE", "EMPLEADO", "MIXTO");
    private static final List<String> ESTADOS = List.of("TODAS", "ACTIVA", "CANCELADA");

    private final RepositorioTarjetasRfid repositorio;
    private final RepositorioConfiguracion configuracion;
    private final TransactionTemplate lectura;
    private final TransactionTemplate escritura;
    private final PublicadorTarjetasRfid1 publicador;
    private final Clock reloj;

    @Autowired
    public ServicioTarjetasRfid1(
            RepositorioTarjetasRfid repositorio,
            RepositorioConfiguracion configuracion,
            PlatformTransactionManager administradorTransacciones,
            PublicadorTarjetasRfid1 publicador) {
        this(repositorio, configuracion, administradorTransacciones, publicador, Clock.systemUTC());
    }

    ServicioTarjetasRfid1(
            RepositorioTarjetasRfid repositorio,
            RepositorioConfiguracion configuracion,
            PlatformTransactionManager administradorTransacciones,
            PublicadorTarjetasRfid1 publicador,
            Clock reloj) {
        this.repositorio = repositorio;
        this.configuracion = configuracion;
        this.publicador = publicador;
        this.reloj = reloj;
        this.lectura = new TransactionTemplate(administradorTransacciones);
        this.lectura.setReadOnly(true);
        this.lectura.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
        this.escritura = new TransactionTemplate(administradorTransacciones);
    }

    /**
     * Busca hasta diez candidatos RFID con dos caracteres o más, incluidos los no elegibles con su motivo.
     */
    public List<CandidatoPersona> buscarPersonas(String tipoEntidad, String busqueda, PrincipalPropietario principal) {
        exigirAccesoAdministrativo(principal);
        String tipo = validarTipo(tipoEntidad);
        String termino = busqueda == null ? "" : busqueda.strip();
        if (termino.codePointCount(0, termino.length()) < 2) {
            return List.of();
        }
        validarTermino(termino);
        try {
            List<CandidatoPersona> candidatos = lectura.execute(estado -> {
                TipoEstacionamiento modalidad = tipoEstacionamiento(configuracion.obtener());
                String tipoPermitido = PoliticaModalidadRfid1.tipoCandidato(modalidad, tipo);
                if (tipoPermitido == null) {
                    return List.of();
                }
                return repositorio.buscarPersonas(tipoPermitido, termino, MAXIMO_CANDIDATOS).stream()
                        .map(CandidatoPersona::desde).toList();
            });
            return candidatos == null ? List.of() : candidatos;
        } catch (DataAccessException excepcion) {
            throw servicioNoDisponible();
        }
    }

    /** Indica el tipo de estacionamiento que la pantalla necesita para buscar personas. */
    public Modalidad consultarModalidad(PrincipalPropietario principal) {
        exigirAccesoAdministrativo(principal);
        try {
            TipoEstacionamiento modalidad = lectura.execute(estado ->
                    tipoEstacionamiento(configuracion.obtener()));
            if (modalidad == null) {
                throw servicioNoDisponible();
            }
            return new Modalidad(modalidad);
        } catch (DataAccessException excepcion) {
            throw servicioNoDisponible();
        }
    }

    /** Muestra una página de tarjetas y sus números de identificación a quien tiene permiso. */
    public Pagina listar(
            String tipoEntidad, String estado, String paginaSolicitada, String busqueda, PrincipalPropietario principal) {
        exigirAccesoAdministrativo(principal);
        String tipo = validarTipo(tipoEntidad);
        String filtro = validarEstado(estado);
        int pagina = validarPagina(paginaSolicitada);
        if (busqueda != null) {
            validarTermino(busqueda);
        }
        String termino = busqueda == null ? "" : recortarBusqueda(busqueda);
        boolean incluirUid = principal.rol() == RolCuenta.DUENO;
        long offset = (long) (pagina - 1) * TAMANO_PAGINA;
        if (offset > Integer.MAX_VALUE) {
            throw error(HttpStatus.BAD_REQUEST, "PAGINA_NO_VALIDA", "La página indicada no es válida.");
        }
        try {
            Pagina resultado = lectura.execute(transaccion -> {
                long total = repositorio.contarTarjetas(tipo, filtro, termino, incluirUid);
                List<Tarjeta> items = repositorio.listarTarjetas(
                                tipo, filtro, termino, (int) offset, TAMANO_PAGINA, incluirUid).stream()
                        .map(tarjeta -> Tarjeta.desde(tarjeta, incluirUid)).toList();
                int totalPaginas = total == 0 ? 0 : Math.toIntExact((total + TAMANO_PAGINA - 1) / TAMANO_PAGINA);
                return new Pagina(items, pagina, TAMANO_PAGINA, total, totalPaginas);
            });
            if (resultado == null) {
                throw servicioNoDisponible();
            }
            return resultado;
        } catch (DataAccessException | ArithmeticException excepcion) {
            throw servicioNoDisponible();
        }
    }

    /** Busca los datos privados de una tarjeta y su número de identificación para una cuenta autorizada. */
    public Tarjeta consultar(long asociacionId, PrincipalPropietario principal) {
        exigirAccesoAdministrativo(principal);
        if (asociacionId < 1) {
            throw tarjetaNoEncontrada();
        }
        boolean incluirUid = principal.rol() == RolCuenta.DUENO;
        try {
            Optional<Tarjeta> tarjeta = lectura.execute(estado -> repositorio
                    .buscarTarjeta(asociacionId, incluirUid)
                    .map(valor -> Tarjeta.desde(valor, incluirUid)));
            if (tarjeta == null) {
                throw servicioNoDisponible();
            }
            return tarjeta.orElseThrow(ServicioTarjetasRfid1::tarjetaNoEncontrada);
        } catch (DataAccessException excepcion) {
            throw servicioNoDisponible();
        }
    }

    /** Cancela la asociación de una tarjeta y avisa a las pantallas después de guardar el cambio. */
    public Cancelacion cancelar(long asociacionId, PrincipalPropietario principal) {
        exigirAccesoAdministrativo(principal);
        if (asociacionId < 1) {
            throw tarjetaNoEncontrada();
        }
        try {
            ResultadoCancelacionTarjetaRfid1 resultado = escritura.execute(
                    estado -> repositorio.cancelarTarjeta(asociacionId, reloj.instant()));
            if (resultado == null) {
                throw servicioNoDisponible();
            }
            if (resultado.codigoError() != null) {
                throw errorCancelacion(resultado.codigoError());
            }
            publicador.publicarSiActualizadas(!resultado.repetida());
            return new Cancelacion(asociacionId, resultado.estado());
        } catch (DataAccessException excepcion) {
            throw servicioNoDisponible();
        }
    }

    private static String validarTipo(String tipo) {
        if (!TIPOS.contains(tipo)) {
            throw error(HttpStatus.BAD_REQUEST, "TIPO_ENTIDAD_NO_VALIDO", "Elige CLIENTE, EMPLEADO o MIXTO.");
        }
        return tipo;
    }

    private static String validarEstado(String estado) {
        String valor = estado == null ? "TODAS" : estado;
        if (!ESTADOS.contains(valor)) {
            throw error(HttpStatus.BAD_REQUEST, "ESTADO_TARJETA_NO_VALIDO", "Elige un estado de tarjeta válido.");
        }
        return valor;
    }

    private static void validarTermino(String termino) {
        if (termino.length() > 100 || termino.codePoints().anyMatch(Character::isISOControl)) {
            throw error(HttpStatus.BAD_REQUEST, "BUSQUEDA_NO_VALIDA", "Revisa el texto de búsqueda.");
        }
    }

    private static String recortarBusqueda(String termino) {
        int inicio = 0;
        int fin = termino.length();
        while (inicio < fin && esEspacioBusqueda(termino.codePointAt(inicio))) {
            inicio += Character.charCount(termino.codePointAt(inicio));
        }
        while (fin > inicio && esEspacioBusqueda(termino.codePointBefore(fin))) {
            fin -= Character.charCount(termino.codePointBefore(fin));
        }
        return termino.substring(inicio, fin);
    }

    private static boolean esEspacioBusqueda(int punto) {
        return Character.isWhitespace(punto) || Character.isSpaceChar(punto) || punto == 0xFEFF;
    }

    private static int validarPagina(String texto) {
        if (texto == null) {
            return 1;
        }
        try {
            int pagina = Integer.parseInt(texto);
            if (pagina > 0) {
                return pagina;
            }
        } catch (NumberFormatException excepcion) {
            // Se traduce a un error público genérico.
        }
        throw error(HttpStatus.BAD_REQUEST, "PAGINA_NO_VALIDA", "La página indicada no es válida.");
    }

    private static void exigirAccesoAdministrativo(PrincipalPropietario principal) {
        if (principal == null) {
            throw error(HttpStatus.UNAUTHORIZED, "SESION_NO_VIGENTE", "Inicia sesión para continuar.");
        }
        if (principal.rol() != RolCuenta.DUENO && principal.rol() != RolCuenta.OPERADOR) {
            throw error(HttpStatus.FORBIDDEN, "PERMISO_INSUFICIENTE", "No tienes acceso para hacer este cambio.");
        }
    }

    private static TipoEstacionamiento tipoEstacionamiento(ConfiguracionPersistida actual) {
        return actual == null || actual.estado() == null
                || !"CONFIGURADA".equals(actual.estado().name()) ? null : actual.tipoEstacionamiento();
    }

    private static RuntimeException errorCancelacion(String codigo) {
        return switch (codigo) {
            case "TARJETA_NO_ENCONTRADA" -> tarjetaNoEncontrada();
            case "TARJETA_NO_ACTIVA" -> error(HttpStatus.CONFLICT, codigo, "La tarjeta ya no está activa.");
            default -> servicioNoDisponible();
        };
    }

    private static RuntimeException tarjetaNoEncontrada() {
        return error(HttpStatus.NOT_FOUND, "TARJETA_NO_ENCONTRADA", "No encontramos la tarjeta indicada.");
    }

    private static ErrorConfiguracion servicioNoDisponible() {
        return error(HttpStatus.SERVICE_UNAVAILABLE, "SERVICIO_NO_DISPONIBLE",
                "No pudimos completar la operación de tarjetas.");
    }

    private static ErrorConfiguracion error(HttpStatus estado, String codigo, String mensaje) {
        return new ErrorConfiguracion(estado, mensaje, codigo);
    }
}
