package mx.smartparking.ownerconsole.controlador.transferencia;

import java.util.UUID;
import java.util.function.Consumer;
import javafx.scene.Node;
import javafx.stage.Stage;
import mx.smartparking.ownerconsole.controlador.EjecutorJavaFx;
import mx.smartparking.ownerconsole.controlador.configuracion.ControladorAsistenteConfiguracion;
import mx.smartparking.ownerconsole.controlador.configuracion.MensajesAvisoCorreo;
import mx.smartparking.ownerconsole.modelo.BorradorConfiguracion;
import mx.smartparking.ownerconsole.modelo.DatosPanel;
import mx.smartparking.ownerconsole.modelo.EstadoConfiguracion;
import mx.smartparking.ownerconsole.servicio.ClienteConfiguracionPropietario;
import mx.smartparking.ownerconsole.servicio.ClienteTransferenciaPropietario;
import mx.smartparking.ownerconsole.servicio.FalloApi;
import mx.smartparking.ownerconsole.servicio.MapeadorSolicitudConfiguracion;
import mx.smartparking.ownerconsole.servicio.PayloadConfiguracion;
import mx.smartparking.ownerconsole.servicio.ResultadoTransicion;
import mx.smartparking.ownerconsole.vista.VistaPanel;
import mx.smartparking.ownerconsole.vista.VistaRecuperacionTransferencia;

/** Coordina la desvinculación inmediata, recuperación y finalización del reemplazo. */
public final class ControladorTransferenciaPropietario {

    private final ClienteTransferenciaPropietario cliente;
    private final ClienteConfiguracionPropietario clienteConfiguracion;
    private final EjecutorJavaFx ejecutor;
    private final Consumer<Node> mostrarVista;
    private final ControladorAsistenteConfiguracion asistente;
    private final Consumer<String> alCompletar;
    private final Consumer<String> alMostrarConexion;
    private final Consumer<String> alCargarPanel;
    private final MapeadorSolicitudConfiguracion mapeador = new MapeadorSolicitudConfiguracion();
    private final ControladorInicioTransferenciaPropietario controladorInicio;
    private VistaRecuperacionTransferencia vistaRecuperacion;
    private BorradorConfiguracion borradorPendiente;
    private String grant;
    private String claveCompletar;
    private long revisionClave = -1;
    private boolean requiereConsultaAntesDeReintentar;

    public ControladorTransferenciaPropietario(
            Stage escenario,
            ClienteTransferenciaPropietario cliente,
            ClienteConfiguracionPropietario clienteConfiguracion,
            EjecutorJavaFx ejecutor,
            Consumer<Node> mostrarVista,
            ControladorAsistenteConfiguracion asistente,
            Consumer<String> alCompletar,
            Consumer<String> alMostrarConexion,
            Consumer<String> alCargarPanel) {
        this.cliente = cliente;
        this.clienteConfiguracion = clienteConfiguracion;
        this.ejecutor = ejecutor;
        this.mostrarVista = mostrarVista;
        this.asistente = asistente;
        this.alCompletar = alCompletar;
        this.alMostrarConexion = alMostrarConexion;
        this.alCargarPanel = alCargarPanel;
        controladorInicio = new ControladorInicioTransferenciaPropietario(
                escenario,
                cliente,
                clienteConfiguracion,
                ejecutor,
                alMostrarConexion,
                alCargarPanel,
                this::iniciarAsistenteTrasDesvincular,
                this::iniciarRecuperacion);
    }

    public void preparar(DatosPanel panel, VistaPanel vistaPanel) {
        controladorInicio.preparar(panel, vistaPanel);
    }

    /**
     * abre la recuperación sin usar datos escritos anteriormente
     * al obtener una autorización el asistente empieza con datos nuevos
     */
    public void iniciarRecuperacion(String mensaje) {
        borradorPendiente = null;
        mostrarRecuperacion(null, mensaje);
    }

    /**
     * abre la recuperación y conserva los datos escritos cuando los recibe
     * permite continuar con esos datos después de obtener una autorización
     */
    public void iniciarRecuperacion(BorradorConfiguracion borrador, String mensaje) {
        borradorPendiente = borrador;
        mostrarRecuperacion(borrador, mensaje);
    }

    /** Borra secretos retenidos y libera las referencias sensibles de esta transferencia. */
    public void limpiar() {
        controladorInicio.limpiar();
        if (vistaRecuperacion != null) {
            vistaRecuperacion.limpiarContrasena();
            vistaRecuperacion = null;
        }
        if (borradorPendiente != null) {
            borradorPendiente.limpiarSecretos();
            borradorPendiente = null;
        }
        grant = null;
        claveCompletar = null;
        revisionClave = -1;
        requiereConsultaAntesDeReintentar = false;
    }

    private void iniciarAsistenteTrasDesvincular(ResultadoTransicion resultado) {
        if (!EstadoConfiguracion.TRANSFERENCIA_PENDIENTE.name().equals(resultado.estado())) {
            alCargarPanel.accept("No pudimos iniciar el cambio. Actualiza la pantalla e inténtalo de nuevo.");
            return;
        }
        grant = resultado.grant();
        borradorPendiente = null;
        claveCompletar = null;
        asistente.mostrarTransferencia(new BorradorConfiguracion(), this::completarTransferencia, false);
        asistente.mostrarEstado(
                ControladorInicioTransferenciaPropietario.textoAvisoTransferencia(resultado.avisoCorreo()), false);
    }

    private void mostrarRecuperacion(BorradorConfiguracion borrador, String mensaje) {
        vistaRecuperacion = new VistaRecuperacionTransferencia(this::recuperar);
        vistaRecuperacion.mostrarEstado(mensaje, false);
        mostrarVista.accept(vistaRecuperacion);
        if (borrador != null) {
            borradorPendiente = borrador;
        }
    }

    private void recuperar(String contrasenaAdministrativa) {
        if (contrasenaAdministrativa == null || contrasenaAdministrativa.isEmpty()) {
            vistaRecuperacion.mostrarEstado("Escribe la contraseña de administración anterior.", false);
            return;
        }
        vistaRecuperacion.limpiarContrasena();
        vistaRecuperacion.mostrarEstado("Comprobando la contraseña…", true);
        boolean conservar = borradorPendiente != null;
        ejecutor.ejecutar(() -> cliente.recuperarTransferencia(contrasenaAdministrativa), resultado -> {
            grant = resultado.grant();
            claveCompletar = null;
            revisionClave = -1;
            requiereConsultaAntesDeReintentar = false;
            BorradorConfiguracion borrador = conservar ? borradorPendiente : new BorradorConfiguracion();
            asistente.mostrarTransferencia(borrador, this::completarTransferencia, conservar);
            asistente.mostrarEstado(
                    conservar
                            ? "Ya puedes continuar el cambio. Revisa la información antes de guardarla."
                            : "",
                    false);
        }, error -> {
            if (incierto(error)) {
                resolverRecuperacionIncierta(conservar);
            } else {
                vistaRecuperacion.mostrarEstado(mensaje(error), false);
            }
        });
    }

    private void resolverRecuperacionIncierta(boolean conservar) {
        alMostrarConexion.accept("Comprobando qué pasó con el cambio…");
        ejecutor.ejecutar(clienteConfiguracion::consultarEstado, estado -> {
            if (estado == EstadoConfiguracion.TRANSFERENCIA_PENDIENTE) {
                String mensaje = "El cambio sigue pendiente. Escribe otra vez la contraseña de administración para continuar.";
                if (conservar) {
                    iniciarRecuperacion(borradorPendiente, mensaje);
                } else {
                    iniciarRecuperacion(mensaje);
                }
            } else if (estado == EstadoConfiguracion.CONFIGURADA) {
                completar("DESCONOCIDO");
            } else {
                alMostrarConexion.accept("El cambio ya no está pendiente. Actualiza la pantalla para ver cómo continuar.");
            }
        }, error -> alMostrarConexion.accept("No pudimos comprobar si el cambio sigue pendiente."));
    }

    private void completarTransferencia(BorradorConfiguracion borrador) {
        if (requiereConsultaAntesDeReintentar) {
            borradorPendiente = borrador;
            resolverFinalizacionIncierta();
            return;
        }
        if (claveCompletar == null || revisionClave != borrador.revision()) {
            claveCompletar = UUID.randomUUID().toString();
            revisionClave = borrador.revision();
        }
        PayloadConfiguracion payload = mapeador.mapear(borrador);
        asistente.mostrarEstado("Guardando la configuración…", true);
        String clave = claveCompletar;
        ejecutor.ejecutar(
                () -> cliente.completarTransferencia(payload, grant, clave),
                resultado -> {
                    if (EstadoConfiguracion.CONFIGURADA.name().equals(resultado.estado())) {
                        completar(resultado.avisoCorreo());
                    } else {
                        borradorPendiente = borrador;
                        requiereConsultaAntesDeReintentar = true;
                        resolverFinalizacionIncierta();
                    }
                },
                error -> {
                    if (incierto(error) || error instanceof FalloApi fallo
                            && (fallo.estadoHttp() == 403 || fallo.estadoHttp() == 409)) {
                        borradorPendiente = borrador;
                        requiereConsultaAntesDeReintentar = true;
                        resolverFinalizacionIncierta();
                    } else {
                        claveCompletar = null;
                        asistente.mostrarEstado(mensaje(error), false);
                    }
                });
    }

    /**
     * comprueba qué ocurrió cuando no se pudo confirmar el final del cambio
     * si sigue pendiente conserva lo escrito y pide obtener otra autorización
     */
    private void resolverFinalizacionIncierta() {
        asistente.mostrarEstado("Comprobando qué pasó antes de continuar…", true);
        ejecutor.ejecutar(clienteConfiguracion::consultarEstado, estado -> {
            if (estado == EstadoConfiguracion.CONFIGURADA) {
                completar("DESCONOCIDO");
            } else if (estado == EstadoConfiguracion.TRANSFERENCIA_PENDIENTE) {
                requiereConsultaAntesDeReintentar = true;
                iniciarRecuperacion(
                        borradorPendiente,
                        "El cambio sigue pendiente. Escribe la contraseña de administración anterior para continuar. Conservamos lo que ya escribiste en esta ventana.");
            } else {
                asistente.mostrarEstado("No pudimos confirmar el cambio. Conservamos lo que ya escribiste en esta ventana.", false);
            }
        }, error -> asistente.mostrarEstado(
                "No pudimos comprobar si se guardaron los cambios. Conservamos lo que escribiste; revisa tu conexión antes de continuar.", false));
    }

    private void completar(String avisoCorreo) {
        grant = null;
        claveCompletar = null;
        borradorPendiente = null;
        requiereConsultaAntesDeReintentar = false;
        asistente.limpiar();
        alCompletar.accept(MensajesAvisoCorreo.describirBienvenida(avisoCorreo));
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
