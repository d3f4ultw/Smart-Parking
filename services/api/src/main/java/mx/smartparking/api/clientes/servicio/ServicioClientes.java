package mx.smartparking.api.clientes.servicio;

import java.util.Locale;
import java.util.UUID;
import java.util.regex.Pattern;
import mx.smartparking.api.clientes.configuracion.CatalogoMembresia;
import mx.smartparking.api.clientes.modelo.ClientePortal;
import mx.smartparking.api.clientes.modelo.EstadoMembresia;
import mx.smartparking.api.clientes.modelo.MembresiaPortal;
import mx.smartparking.api.clientes.modelo.PlanMembresia;
import mx.smartparking.api.clientes.modelo.PortalCliente;
import mx.smartparking.api.clientes.membresia.modelo.CheckoutPendientePortal;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.PublicadorEventosClientes;
import mx.smartparking.api.persistencia.CuentaPersistida;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.persistencia.membresia.RepositorioMembresias;
import mx.smartparking.api.persistencia.membresia.ResumenMembresiaPersistido;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.annotation.Transactional;

/** Aplica reglas de registro, consulta personal y cambio de contraseña de clientes. */
@Service
public class ServicioClientes {

    private static final int MAXIMO_NOMBRES = 120;
    private static final int MAXIMO_APELLIDOS = 80;
    private static final int MAXIMO_CORREO = 254;
    private static final int MINIMO_PUNTOS_CONTRASENA = 10;
    private static final Pattern CORREO_VALIDO = Pattern.compile("^[^\\s@]+@[^\\s@.]+(?:\\.[^\\s@.]+)+$");

    private final RepositorioCuentas cuentas;
    private final RepositorioMembresias membresias;
    private final PasswordEncoder codificador;
    private final CatalogoMembresia catalogo;
    private final PublicadorEventosClientes publicadorEventos;

    public ServicioClientes(
            RepositorioCuentas cuentas,
            RepositorioMembresias membresias,
            PasswordEncoder codificador,
            CatalogoMembresia catalogo,
            PublicadorEventosClientes publicadorEventos) {
        this.cuentas = cuentas;
        this.membresias = membresias;
        this.codificador = codificador;
        this.catalogo = catalogo;
        this.publicadorEventos = publicadorEventos;
    }

    /** Crea la cuenta activa del cliente sin abrir su sesión ni contratar una membresía. */
    @Transactional
    public UUID registrarCliente(
            String nombres,
            String primerApellido,
            String segundoApellido,
            String correo,
            String contrasena) {
        String nombresValidados = validarTexto(nombres, MAXIMO_NOMBRES);
        String primerApellidoValidado = validarTexto(primerApellido, MAXIMO_APELLIDOS);
        String segundoApellidoValidado = validarSegundoApellido(segundoApellido);
        String correoNormalizado = normalizarCorreo(correo);
        validarContrasena(contrasena);
        String hashContrasena = codificador.encode(contrasena);
        UUID clienteId = cuentas.crearCliente(
                nombresValidados, primerApellidoValidado, segundoApellidoValidado,
                correoNormalizado, hashContrasena);
        publicarRegistroDespuesDelCommit();
        return clienteId;
    }

    private void publicarRegistroDespuesDelCommit() {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            publicadorEventos.clienteRegistrado();
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                publicadorEventos.clienteRegistrado();
            }
        });
    }

    /** Busca los datos de la cuenta activa y la información de su membresía para mostrarlos al cliente. */
    @Transactional(readOnly = true)
    public PortalCliente consultarPortal(UUID clienteId) {
        CuentaPersistida cuenta = cuentas.obtener(clienteId)
                .filter(this::esClienteActivo)
                .orElseThrow(ServicioClientes::clienteNoEncontrado);
        ClientePortal perfil = new ClientePortal(
                cuenta.id(), cuenta.nombres(), cuenta.primerApellido(), cuenta.segundoApellido(), cuenta.correo());
        PlanMembresia plan = new PlanMembresia(
                catalogo.productoId(), catalogo.precioId(), catalogo.nombre(), catalogo.importeMenorUnidad(),
                catalogo.moneda(), catalogo.intervalo(), catalogo.intervaloCantidad());
        ResumenMembresiaPersistido resumen = membresias.consultarResumenMembresia(clienteId);
        CheckoutPendientePortal checkoutPendiente = resumen.intentoCheckoutPendienteId() == null
                ? null
                : new CheckoutPendientePortal(resumen.intentoCheckoutPendienteId(),
                        resumen.estadoCheckoutPendiente(), resumen.checkoutExpiraEn());
        MembresiaPortal membresia = new MembresiaPortal(
                estadoMembresia(resumen.estado()), plan,
                resumen.periodoInicio(), resumen.periodoFin(), resumen.siguienteCobroEn(),
                resumen.cancelacionAlFinal(), resumen.puedeComprar(), checkoutPendiente);
        return new PortalCliente(perfil, membresia);
    }

    private static EstadoMembresia estadoMembresia(String estado) {
        try {
            return EstadoMembresia.valueOf(estado);
        } catch (IllegalArgumentException | NullPointerException excepcion) {
            return EstadoMembresia.INACTIVA;
        }
    }

    /**
     * Comprueba la contraseña actual y guarda la nueva junto con los cambios necesarios para cerrar
     * accesos anteriores.
     */
    @Transactional
    public void cambiarContrasena(UUID clienteId, String contrasenaActual, String nuevaContrasena) {
        CuentaPersistida cuenta = cuentas.obtener(clienteId)
                .filter(this::esClienteActivo)
                .orElseThrow(ServicioClientes::clienteNoEncontrado);
        if (contrasenaActual == null || cuenta.hashContrasenaAcceso() == null
                || !codificador.matches(contrasenaActual, cuenta.hashContrasenaAcceso())) {
            throw error(HttpStatus.UNAUTHORIZED, "CREDENCIALES_NO_VALIDAS",
                    "No pudimos verificar tu contraseña actual.");
        }
        validarContrasena(nuevaContrasena);
        if (cuenta.revisionAcceso() == Long.MAX_VALUE) {
            throw error(HttpStatus.CONFLICT, "CUENTA_EN_CONFLICTO",
                    "No pudimos cambiar tu contraseña. Actualiza la sesión e inténtalo de nuevo.");
        }
        String hashNuevo = codificador.encode(nuevaContrasena);
        if (!cuentas.actualizarContrasenaCliente(clienteId, cuenta.revisionAcceso(), hashNuevo)) {
            throw error(HttpStatus.CONFLICT, "CUENTA_EN_CONFLICTO",
                    "La información de la cuenta cambió. Inicia sesión de nuevo.");
        }
    }

    private boolean esClienteActivo(CuentaPersistida cuenta) {
        return cuenta.rol() == RolCuenta.CLIENTE && cuenta.activa();
    }

    private static String validarTexto(String texto, int maximoPuntos) {
        if (texto == null) {
            throw datosRegistroNoValidos();
        }
        String valor = texto.strip();
        int puntos = valor.codePointCount(0, valor.length());
        if (puntos == 0 || puntos > maximoPuntos || valor.codePoints().anyMatch(Character::isISOControl)) {
            throw datosRegistroNoValidos();
        }
        return valor;
    }

    private static String validarSegundoApellido(String segundoApellido) {
        if (segundoApellido == null || segundoApellido.isBlank()) {
            return null;
        }
        return validarTexto(segundoApellido, MAXIMO_APELLIDOS);
    }

    private static String normalizarCorreo(String correo) {
        if (correo == null) {
            throw datosRegistroNoValidos();
        }
        String normalizado = correo.strip().toLowerCase(Locale.ROOT);
        if (normalizado.codePointCount(0, normalizado.length()) > MAXIMO_CORREO
                || !CORREO_VALIDO.matcher(normalizado).matches()
                || normalizado.codePoints().anyMatch(punto ->
                        Character.isISOControl(punto) || Character.isWhitespace(punto))) {
            throw datosRegistroNoValidos();
        }
        return normalizado;
    }

    private static void validarContrasena(String contrasena) {
        if (contrasena == null
                || contrasena.codePointCount(0, contrasena.length()) < MINIMO_PUNTOS_CONTRASENA) {
            throw error(HttpStatus.BAD_REQUEST, "CONTRASENA_NO_VALIDA",
                    "La contraseña debe tener al menos 10 caracteres.");
        }
    }

    private static ErrorConfiguracion clienteNoEncontrado() {
        return error(HttpStatus.NOT_FOUND, "CLIENTE_NO_ENCONTRADO", "No encontramos esta cuenta de cliente.");
    }

    private static ErrorConfiguracion datosRegistroNoValidos() {
        return error(HttpStatus.BAD_REQUEST, "DATOS_REGISTRO_NO_VALIDOS",
                "Revisa los datos y vuelve a intentarlo.");
    }

    private static ErrorConfiguracion error(HttpStatus estado, String codigo, String mensaje) {
        return new ErrorConfiguracion(estado, mensaje, codigo);
    }
}
