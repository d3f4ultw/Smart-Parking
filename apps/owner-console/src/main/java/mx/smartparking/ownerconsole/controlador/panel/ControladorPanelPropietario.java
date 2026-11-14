package mx.smartparking.ownerconsole.controlador.panel;

import java.util.function.BiConsumer;
import java.util.function.Consumer;
import javafx.scene.Node;
import mx.smartparking.ownerconsole.controlador.EjecutorJavaFx;
import mx.smartparking.ownerconsole.modelo.DatosPanel;
import mx.smartparking.ownerconsole.modelo.EdicionEstacionamiento;
import mx.smartparking.ownerconsole.modelo.EstadoConfiguracion;
import mx.smartparking.ownerconsole.servicio.ClienteConfiguracionPropietario;
import mx.smartparking.ownerconsole.servicio.FalloApi;
import mx.smartparking.ownerconsole.vista.VistaPanel;

/** carga la información del estacionamiento y permite cambiar su nombre, tipo y horario desde el panel. */
public final class ControladorPanelPropietario {

    private final ClienteConfiguracionPropietario cliente;
    private final EjecutorJavaFx ejecutor;
    private final Consumer<Node> mostrarVista;
    private final Consumer<String> alMostrarAcceso;
    private final Consumer<String> alMostrarConexion;
    private final BiConsumer<DatosPanel, VistaPanel> alIniciarTransferencia;
    private final Consumer<VistaPanel> alCerrarSesion;
    private final Consumer<String> alTransferenciaPendiente;
    private DatosPanel panel;
    private VistaPanel vistaPanel;
    private String nombreRenombrado;
    private EdicionEstacionamiento edicionPendiente;

    public ControladorPanelPropietario(
            ClienteConfiguracionPropietario cliente,
            EjecutorJavaFx ejecutor,
            Consumer<Node> mostrarVista,
            Consumer<String> alMostrarAcceso,
            Consumer<String> alMostrarConexion,
            BiConsumer<DatosPanel, VistaPanel> alIniciarTransferencia,
            Consumer<VistaPanel> alCerrarSesion,
            Consumer<String> alTransferenciaPendiente) {
        this.cliente = cliente;
        this.ejecutor = ejecutor;
        this.mostrarVista = mostrarVista;
        this.alMostrarAcceso = alMostrarAcceso;
        this.alMostrarConexion = alMostrarConexion;
        this.alIniciarTransferencia = alIniciarTransferencia;
        this.alCerrarSesion = alCerrarSesion;
        this.alTransferenciaPendiente = alTransferenciaPendiente;
    }

    public void cargarPanel(String mensajeInicial) {
        alMostrarConexion.accept("Cargando tu información…");
        ejecutor.ejecutar(cliente::consultarPanel, datos -> {
            panel = datos;
            vistaPanel = new VistaPanel(
                    this::renombrar,
                    this::actualizarDatosEstacionamiento,
                    () -> alIniciarTransferencia.accept(panel, vistaPanel),
                    () -> alCerrarSesion.accept(vistaPanel));
            vistaPanel.mostrarPanel(datos);
            vistaPanel.mostrarEstado(mensajeInicial, false);
            mostrarVista.accept(vistaPanel);
        }, error -> {
            if (error instanceof FalloApi fallo && fallo.estadoHttp() == 401) {
                alMostrarAcceso.accept("Tu acceso venció. Inicia sesión de nuevo.");
            } else if (incierto(error)) {
                alMostrarConexion.accept("No pudimos cargar tu información. Inténtalo de nuevo.");
            } else {
                alMostrarAcceso.accept(mensaje(error));
            }
        });
    }

    private void renombrar(String nombre) {
        String valor = nombre == null ? "" : nombre.trim();
        if (valor.isEmpty() || valor.length() > 120) {
            vistaPanel.mostrarErrorNombre("Escribe un nombre más corto.");
            return;
        }
        if (valor.equals(panel.estacionamiento().nombre())) {
            vistaPanel.mostrarPanel(panel);
            return;
        }
        nombreRenombrado = valor;
        vistaPanel.mostrarEstado("Guardando el nombre…", true);
        ejecutor.ejecutar(
                () -> cliente.renombrarEstacionamiento(valor, panel),
                datos -> {
                    panel = datos;
                    vistaPanel.mostrarPanel(datos);
                    vistaPanel.mostrarAvisoTemporal("Nombre actualizado.");
                },
                error -> {
                    if (incierto(error) || error instanceof FalloApi fallo && fallo.estadoHttp() == 412) {
                        resolverRenombradoIncierto();
                    } else {
                        vistaPanel.mostrarEstado(mensaje(error), false);
                    }
                });
    }

    private void actualizarDatosEstacionamiento(EdicionEstacionamiento edicion) {
        if (coincideEdicion(edicion, panel)) {
            return;
        }
        edicionPendiente = edicion;
        vistaPanel.mostrarEstado("Guardando el tipo y el horario…", true);
        ejecutor.ejecutar(
                () -> cliente.actualizarDatosEstacionamiento(edicion, panel),
                datos -> {
                    panel = datos;
                    vistaPanel.mostrarPanel(datos);
                    vistaPanel.mostrarAvisoTemporal("Tipo y horario actualizados.");
                },
                error -> {
                    if (incierto(error) || error instanceof FalloApi fallo && fallo.estadoHttp() == 412) {
                        resolverActualizacionDatosIncierta();
                    } else {
                        vistaPanel.mostrarEstado(mensaje(error), false);
                    }
                });
    }

    private void resolverActualizacionDatosIncierta() {
        vistaPanel.mostrarEstado("Comprobando si se guardaron los cambios…", true);
        ejecutor.ejecutar(cliente::consultarEstado, estado -> {
            if (estado == EstadoConfiguracion.CONFIGURADA) {
                ejecutor.ejecutar(cliente::consultarPanel, datos -> {
                    panel = datos;
                    vistaPanel.mostrarPanel(datos);
                    if (coincideEdicion(edicionPendiente, datos)) {
                        vistaPanel.mostrarAvisoTemporal("Tipo y horario actualizados.");
                    } else {
                        vistaPanel.mostrarEstado(
                                "No pudimos confirmar el cambio. Revisa la información antes de volver a intentarlo.",
                                false);
                    }
                }, this::manejarErrorPanel);
            } else if (estado == EstadoConfiguracion.TRANSFERENCIA_PENDIENTE) {
                alTransferenciaPendiente.accept(
                        "El propietario actual ya no tiene acceso. Escribe la contraseña de administración para continuar el cambio.");
            } else {
                alMostrarAcceso.accept("No pudimos abrir tu cuenta. Inicia sesión otra vez.");
            }
        }, error -> vistaPanel.mostrarEstado(
                "No pudimos comprobar si se guardaron los cambios. Conservamos la información para que puedas revisarla.", false));
    }

    private boolean coincideEdicion(EdicionEstacionamiento edicion, DatosPanel datos) {
        if (edicion == null) {
            return false;
        }
        DatosPanel.Estacionamiento estacionamiento = datos.estacionamiento();
        DatosPanel.Horario horario = estacionamiento.horario();
        return edicion.tipo().equals(estacionamiento.tipo())
                && edicion.modoHorario().equals(horario.modo())
                && edicion.zonaHoraria().equals(horario.zonaHoraria())
                && java.util.Objects.equals(edicion.horaApertura(), horario.horaApertura())
                && java.util.Objects.equals(edicion.horaCierre(), horario.horaCierre());
    }

    private void resolverRenombradoIncierto() {
        vistaPanel.mostrarEstado("Comprobando si se guardó el cambio…", true);
        ejecutor.ejecutar(cliente::consultarEstado, estado -> {
            if (estado == EstadoConfiguracion.CONFIGURADA) {
                ejecutor.ejecutar(cliente::consultarPanel, datos -> {
                    panel = datos;
                    vistaPanel.mostrarPanel(datos);
                    if (datos.estacionamiento().nombre().equals(nombreRenombrado)) {
                        vistaPanel.mostrarAvisoTemporal("Nombre actualizado.");
                    } else {
                        vistaPanel.mostrarEstado(
                                "No pudimos confirmar el cambio. Revisa el nombre antes de volver a intentarlo.",
                                false);
                    }
                }, this::manejarErrorPanel);
            } else if (estado == EstadoConfiguracion.TRANSFERENCIA_PENDIENTE) {
                alTransferenciaPendiente.accept(
                        "El propietario actual ya no tiene acceso. Escribe la contraseña de administración para continuar el cambio.");
            } else {
                alMostrarAcceso.accept("No pudimos abrir tu cuenta. Inicia sesión otra vez.");
            }
        }, error -> vistaPanel.mostrarEstado(
                "No pudimos comprobar si se guardó el cambio. Conservamos el nombre para que puedas revisarlo.", false));
    }

    private void manejarErrorPanel(Throwable error) {
        if (error instanceof FalloApi fallo && fallo.estadoHttp() == 401) {
            alMostrarAcceso.accept("Tu acceso venció. Inicia sesión de nuevo.");
        } else {
            alMostrarConexion.accept(
                    "No pudimos cargar tu información. Revisa tu conexión para continuar.");
        }
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
