package mx.smartparking.ownerconsole.controlador;

import javafx.scene.Node;
import javafx.scene.layout.StackPane;
import javafx.stage.Stage;
import mx.smartparking.ownerconsole.controlador.configuracion.ControladorAsistenteConfiguracion;
import mx.smartparking.ownerconsole.controlador.panel.ControladorPanelPropietario;
import mx.smartparking.ownerconsole.controlador.sesion.ControladorSesionPropietario;
import mx.smartparking.ownerconsole.controlador.transferencia.ControladorTransferenciaPropietario;
import mx.smartparking.ownerconsole.modelo.BorradorConfiguracion;
import mx.smartparking.ownerconsole.modelo.EstadoConfiguracion;
import mx.smartparking.ownerconsole.servicio.ClienteApi;
import mx.smartparking.ownerconsole.servicio.FalloApi;
import mx.smartparking.ownerconsole.servicio.MapeadorSolicitudConfiguracion;
import mx.smartparking.ownerconsole.vista.VistaConexion;

/**
 * inicia la consola y muestra la pantalla que corresponde
 * según la información que recibe del servidor
 */
public final class ControladorAplicacion {

    private final Stage escenario;
    private final StackPane raiz;
    private final ClienteApi clientes;
    private final EjecutorJavaFx ejecutor = new EjecutorJavaFx();
    private final ControladorAsistenteConfiguracion asistente;
    private final ControladorSesionPropietario sesion;
    private final ControladorTransferenciaPropietario transferencia;
    private final ControladorPanelPropietario panel;
    private VistaConexion vistaConexion;

    public ControladorAplicacion(Stage escenario, StackPane raiz, ClienteApi clientes) {
        this.escenario = escenario;
        this.raiz = raiz;
        this.clientes = clientes;
        asistente = new ControladorAsistenteConfiguracion(
                clientes.configuracion(),
                new MapeadorSolicitudConfiguracion(),
                ejecutor,
                this::mostrar,
                this::mostrarAcceso,
                this::iniciarRecuperacionConBorrador,
                this::salirAsistente);
        sesion = new ControladorSesionPropietario(
                clientes.sesion(), ejecutor, this::mostrar, this::cargarPanel, this::mostrarConexion);
        transferencia = new ControladorTransferenciaPropietario(
                escenario,
                clientes.transferencia(),
                clientes.configuracion(),
                ejecutor,
                this::mostrar,
                asistente,
                this::mostrarAcceso,
                this::mostrarConexion,
                this::cargarPanel);
        panel = new ControladorPanelPropietario(
                clientes.configuracion(),
                ejecutor,
                this::mostrar,
                this::mostrarAcceso,
                this::mostrarConexion,
                transferencia::preparar,
                sesion::cerrarSesion,
                transferencia::iniciarRecuperacion);
    }

    /**
     * pregunta al servidor cómo está configurado el sistema al iniciar
     * muestra la pantalla de conexión mientras espera la respuesta
     */
    public void iniciar() {
        consultarEstadoInicial();
    }

    /**
     * borra las contraseñas que quedan en la configuración y el cambio de propietario
     * pide detener las tareas que aún están en curso
     */
    public void cerrar() {
        asistente.limpiar();
        transferencia.limpiar();
        ejecutor.close();
    }

    private void consultarEstadoInicial() {
        mostrarConexion("Cargando la información…", true);
        ejecutor.ejecutar(
                clientes.configuracion()::consultarEstado,
                this::mostrarFlujoPorEstado,
                error -> mostrarConexion(mensaje(error), false));
    }

    /**
     * elige qué pantalla mostrar según la información recibida del servidor
     * decide si debe configurar el sistema, comprobar el acceso o continuar un cambio pendiente
     */
    private void mostrarFlujoPorEstado(EstadoConfiguracion estado) {
        switch (estado) {
            case SIN_CONFIGURAR -> asistente.iniciar();
            case CONFIGURADA -> sesion.comprobarSesion();
            case TRANSFERENCIA_PENDIENTE -> transferencia.iniciarRecuperacion("");
        }
    }

    private void iniciarRecuperacionConBorrador(BorradorConfiguracion borrador) {
        transferencia.iniciarRecuperacion(
                borrador,
                "Conservamos lo que ya escribiste en esta ventana.");
    }

    private void mostrarAcceso(String mensaje) {
        sesion.mostrarAcceso(mensaje);
    }

    private void cargarPanel(String mensaje) {
        panel.cargarPanel(mensaje);
    }

    private void mostrarConexion(String texto) {
        mostrarConexion(texto, false);
    }

    private void mostrarConexion(String texto, boolean ocupado) {
        if (vistaConexion == null) {
            vistaConexion = new VistaConexion(ignorado -> consultarEstadoInicial());
        }
        vistaConexion.mostrarMensaje(texto, ocupado);
        mostrar(vistaConexion);
    }

    private void salirAsistente() {
        escenario.close();
    }

    private String mensaje(Throwable error) {
        return error instanceof FalloApi fallo
                ? fallo.getMessage()
                : "No pudimos completar la acción. Revisa tu conexión e inténtalo de nuevo.";
    }

    private void mostrar(Node vista) {
        raiz.getChildren().setAll(vista);
    }
}
