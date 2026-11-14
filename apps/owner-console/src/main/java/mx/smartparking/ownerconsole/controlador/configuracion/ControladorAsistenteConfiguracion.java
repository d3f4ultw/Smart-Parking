package mx.smartparking.ownerconsole.controlador.configuracion;

import java.util.Map;
import java.util.UUID;
import java.util.function.Consumer;
import javafx.scene.Node;
import mx.smartparking.ownerconsole.controlador.EjecutorJavaFx;
import mx.smartparking.ownerconsole.modelo.BorradorConfiguracion;
import mx.smartparking.ownerconsole.modelo.EstadoConfiguracion;
import mx.smartparking.ownerconsole.modelo.PasoConfiguracion;
import mx.smartparking.ownerconsole.servicio.ClienteConfiguracionPropietario;
import mx.smartparking.ownerconsole.servicio.FalloApi;
import mx.smartparking.ownerconsole.servicio.MapeadorSolicitudConfiguracion;
import mx.smartparking.ownerconsole.servicio.PayloadConfiguracion;
import mx.smartparking.ownerconsole.servicio.ResultadoTransicion;
import mx.smartparking.ownerconsole.vista.configuracion.FormularioAsistente;
import mx.smartparking.ownerconsole.vista.configuracion.VistaAsistente;

/**
 * guía al usuario por los seis pasos de configuración o cambio de propietario
 * comprueba que la información esté lista antes de enviarla
 */
public final class ControladorAsistenteConfiguracion {

    private final ClienteConfiguracionPropietario cliente;
    private final MapeadorSolicitudConfiguracion mapeador;
    private final EjecutorJavaFx ejecutor;
    private final CoordinadorFormularioAsistente formularios = new CoordinadorFormularioAsistente();
    private final Consumer<Node> mostrarVista;
    private final Consumer<String> alCompletar;
    private final Consumer<BorradorConfiguracion> alRecuperarTransferencia;
    private final Runnable alSalir;
    private VistaAsistente vista;
    private BorradorConfiguracion borrador;
    private Consumer<BorradorConfiguracion> alConfirmarTransferencia;
    private boolean transferencia;
    private boolean requiereConsultaAntesDeReintentar;
    private String claveIdempotencia;
    private long revisionClave = -1;

    public ControladorAsistenteConfiguracion(
            ClienteConfiguracionPropietario cliente,
            MapeadorSolicitudConfiguracion mapeador,
            EjecutorJavaFx ejecutor,
            Consumer<Node> mostrarVista,
            Consumer<String> alCompletar,
            Consumer<BorradorConfiguracion> alRecuperarTransferencia,
            Runnable alSalir) {
        this.cliente = cliente;
        this.mapeador = mapeador;
        this.ejecutor = ejecutor;
        this.mostrarVista = mostrarVista;
        this.alCompletar = alCompletar;
        this.alRecuperarTransferencia = alRecuperarTransferencia;
        this.alSalir = alSalir;
    }

    public void iniciar() {
        reemplazarBorrador(new BorradorConfiguracion());
        transferencia = false;
        alConfirmarTransferencia = null;
        requiereConsultaAntesDeReintentar = false;
        claveIdempotencia = null;
        revisionClave = -1;
        mostrarAsistente(false, 0);
    }

    public void mostrarTransferencia(
            BorradorConfiguracion borrador,
            Consumer<BorradorConfiguracion> alConfirmar,
            boolean abrirRevision) {
        reemplazarBorrador(borrador == null ? new BorradorConfiguracion() : borrador);
        transferencia = true;
        alConfirmarTransferencia = alConfirmar;
        requiereConsultaAntesDeReintentar = false;
        claveIdempotencia = null;
        revisionClave = -1;
        mostrarAsistente(true, abrirRevision ? PasoConfiguracion.REVISION.ordinal() : 0);
        if (abrirRevision) {
            actualizarRevision();
        }
    }

    public void mostrarEstado(String texto, boolean ocupado) {
        if (vista != null) {
            vista.mostrarEstado(texto, ocupado);
        }
    }

    public void completar(String avisoCorreo) {
        limpiar();
        transferencia = false;
        requiereConsultaAntesDeReintentar = false;
        claveIdempotencia = null;
        revisionClave = -1;
        String aviso = avisoCorreo == null || avisoCorreo.isBlank() ? "DESCONOCIDO" : avisoCorreo;
        alCompletar.accept(MensajesAvisoCorreo.describirBienvenida(aviso));
    }

    /**
     * deja de usar los datos guardados para el asistente
     * borra las contraseñas guardadas y las que aparecen en los campos
     */
    public void limpiar() {
        if (borrador != null) {
            borrador.limpiarSecretos();
            borrador = null;
        }
        if (vista != null) {
            vista.limpiarContrasenas();
        }
    }

    private void mostrarAsistente(boolean esTransferencia, int pasoInicial) {
        vista = new VistaAsistente(
                esTransferencia,
                this::volverPaso,
                this::avanzarPaso,
                this::finalizarConfiguracion,
                this::salir);
        restaurarFormulario();
        vista.mostrarPaso(pasoInicial);
        mostrarVista.accept(vista);
    }

    private void volverPaso() {
        capturarFormulario();
        vista.mostrarPaso(vista.indice() - 1);
        if (vista.pasoActual() == PasoConfiguracion.REVISION) {
            actualizarRevision();
        }
    }

    private void avanzarPaso() {
        capturarFormulario();
        Map<String, String> errores = formularios.validar(vista.pasoActual(), borrador);
        if (!errores.isEmpty()) {
            vista.mostrarErrores(errores);
            return;
        }
        int siguiente = vista.indice() + 1;
        if (siguiente == PasoConfiguracion.REVISION.ordinal()) {
            actualizarRevision();
        }
        vista.mostrarPaso(siguiente);
    }

    /**
     * comprueba los datos escritos antes de guardarlos o continuar el cambio de propietario
     * al configurar por primera vez puede conservar el identificador si los datos no cambian
     */
    private void finalizarConfiguracion() {
        capturarFormulario();
        Map<String, String> errores = formularios.validarTodo(borrador);
        if (!errores.isEmpty()) {
            int indiceError = formularios.primerIndiceConError(errores);
            vista.mostrarPaso(indiceError);
            vista.mostrarErrores(formularios.filtrarErrores(errores, PasoConfiguracion.values()[indiceError]));
            vista.mostrarEstado(
                    "Hay información por corregir. Te llevamos al primer campo que debes revisar.",
                    false);
            return;
        }
        if (transferencia) {
            vista.mostrarEstado("Guardando la configuración…", true);
            if (alConfirmarTransferencia != null) {
                alConfirmarTransferencia.accept(borrador);
            }
            return;
        }
        if (requiereConsultaAntesDeReintentar) {
            resolverRegistroIncierto();
            return;
        }
        actualizarRevision();
        if (claveIdempotencia == null || revisionClave != borrador.revision()) {
            claveIdempotencia = UUID.randomUUID().toString();
            revisionClave = borrador.revision();
        }
        PayloadConfiguracion payload = mapeador.mapear(borrador);
        vista.mostrarEstado("Guardando la configuración…", true);
        String clave = claveIdempotencia;
        ejecutor.ejecutar(
                () -> cliente.registrar(payload, clave),
                this::resolverRegistro,
                this::manejarFalloRegistro);
    }

    private void resolverRegistro(ResultadoTransicion resultado) {
        if (EstadoConfiguracion.CONFIGURADA.name().equals(resultado.estado())) {
            completar(resultado.avisoCorreo());
        } else {
            requiereConsultaAntesDeReintentar = true;
            resolverRegistroIncierto();
        }
    }

    private void manejarFalloRegistro(Throwable error) {
        if (incierto(error) || error instanceof FalloApi fallo && fallo.estadoHttp() == 409) {
            requiereConsultaAntesDeReintentar = true;
            resolverRegistroIncierto();
        } else {
            claveIdempotencia = null;
            mostrarEstado(mensaje(error), false);
        }
    }

    /**
     * comprueba qué ocurrió al guardar antes de permitir otro intento
     * conserva lo escrito si aún no se guardó o si hace falta recuperar un cambio de propietario
     */
    private void resolverRegistroIncierto() {
        mostrarEstado("Comprobando qué pasó antes de continuar…", true);
        ejecutor.ejecutar(cliente::consultarEstado, estado -> {
            if (estado == EstadoConfiguracion.CONFIGURADA) {
                completar("DESCONOCIDO");
            } else if (estado == EstadoConfiguracion.SIN_CONFIGURAR) {
                requiereConsultaAntesDeReintentar = false;
                mostrarEstado(
                        "Aún no se guardó la configuración. Conservamos lo que escribiste; revisa tu conexión antes de intentarlo de nuevo.",
                        false);
            } else {
                requiereConsultaAntesDeReintentar = true;
                mostrarEstado("El cambio de propietario está pendiente. Conservamos lo que escribiste mientras lo terminas.", false);
                alRecuperarTransferencia.accept(borrador);
            }
        }, error -> mostrarEstado(
                "No pudimos comprobar si se guardó la configuración. Conservamos lo que escribiste; revisa tu conexión antes de continuar.", false));
    }

    private void capturarFormulario() {
        formularios.capturar(vista, borrador);
    }

    private void restaurarFormulario() {
        formularios.restaurar(vista, borrador);
    }

    private void actualizarRevision() {
        formularios.actualizarRevision(vista, borrador);
    }

    private void reemplazarBorrador(BorradorConfiguracion nuevo) {
        if (borrador != null && borrador != nuevo) {
            borrador.limpiarSecretos();
        }
        borrador = nuevo;
    }

    private void salir() {
        limpiar();
        alSalir.run();
    }

    private boolean incierto(Throwable error) {
        return error instanceof FalloApi fallo && fallo.respuestaIncierta();
    }

    private String mensaje(Throwable error) {
        return error instanceof FalloApi fallo
                ? fallo.getMessage()
                : "No pudimos completar la acción. Revisa tu conexión e inténtalo de nuevo.";
    }

}
