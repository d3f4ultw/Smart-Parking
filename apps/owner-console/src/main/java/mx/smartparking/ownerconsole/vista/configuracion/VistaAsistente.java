package mx.smartparking.ownerconsole.vista.configuracion;

import java.util.List;
import java.util.Map;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.ProgressBar;
import javafx.scene.control.ScrollPane;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.StackPane;
import javafx.scene.layout.VBox;
import mx.smartparking.ownerconsole.modelo.PasoConfiguracion;
import mx.smartparking.ownerconsole.vista.VistaComun;

/** Contenedor visual del asistente; las seis vistas poseen y presentan sus propios campos. */
public final class VistaAsistente extends BorderPane {

    private final List<VistaPasoAsistente> vistas = List.of(
            new VistaPasoIdentidad(),
            new VistaPasoAcceso(),
            new VistaPasoAdministrativa(),
            new VistaPasoEstacionamiento(),
            new VistaPasoHorario(),
            new VistaPasoRevision());
    private final Label subtituloPaso = new Label();
    private final Label estado = VistaComun.crearMensajeEstado();
    private final ProgressBar progreso = new ProgressBar(0);
    private final Button anterior = new Button("Anterior");
    private final Button siguiente = new Button("Siguiente");
    private final Button finalizar = new Button("Guardar configuración");
    private final Button salir = new Button("Salir");
    private final Label notaTransferencia = new Label();
    private final StackPane areaPaso = new StackPane();
    private final Runnable alAnterior;
    private final Runnable alSiguiente;
    private final Runnable alFinalizar;
    private final Runnable alSalir;
    private int indice;

    public VistaAsistente(
            boolean transferencia,
            Runnable alAnterior,
            Runnable alSiguiente,
            Runnable alFinalizar,
            Runnable alSalir) {
        this.alAnterior = alAnterior;
        this.alSiguiente = alSiguiente;
        this.alFinalizar = alFinalizar;
        this.alSalir = alSalir;
        notaTransferencia.setText(transferencia
                ? "El propietario anterior ya no tiene acceso. Si sales, necesitarás su contraseña de administración para continuar después."
                : "");
        notaTransferencia.setWrapText(true);
        notaTransferencia.getStyleClass().add("texto-ayuda");
        notaTransferencia.setVisible(transferencia);
        notaTransferencia.setManaged(transferencia);
        construirMarco();
        mostrarPaso(0);
    }

    public int indice() {
        return indice;
    }

    public PasoConfiguracion pasoActual() {
        return vistas.get(indice).paso();
    }

    public int cantidadPasos() {
        return vistas.size();
    }

    /** Devuelve un snapshot que el controlador debe limpiar después de actualizar el borrador. */
    public FormularioAsistente leerFormulario() {
        FormularioAsistente formulario = new FormularioAsistente();
        vistas.forEach(vista -> vista.capturar(formulario));
        return formulario;
    }

    /** Restaura la presentación sin permitir que las vistas accedan al modelo de negocio. */
    public void restaurarFormulario(FormularioAsistente formulario) {
        vistas.forEach(vista -> vista.restaurar(formulario));
        actualizarIndicadorAdministrativo();
    }

    public void mostrarPaso(int nuevoIndice) {
        ocultarSugerenciasZonaHoraria();
        indice = Math.max(0, Math.min(nuevoIndice, vistas.size() - 1));
        if (vistas.get(indice).paso() == PasoConfiguracion.ADMINISTRACION) {
            actualizarIndicadorAdministrativo();
        }
        subtituloPaso.setText("Paso " + (indice + 1) + " de " + vistas.size());
        progreso.setProgress((double) (indice + 1) / vistas.size());
        anterior.setDisable(indice == 0);
        siguiente.setText(indice == vistas.size() - 1 ? "Guardar configuración" : "Siguiente");
        siguiente.setDefaultButton(indice != vistas.size() - 1);
        finalizar.setDefaultButton(indice == vistas.size() - 1);
        siguiente.setVisible(indice != vistas.size() - 1);
        siguiente.setManaged(indice != vistas.size() - 1);
        finalizar.setVisible(indice == vistas.size() - 1);
        finalizar.setManaged(indice == vistas.size() - 1);
        areaPaso.getChildren().setAll(vistas.get(indice).nodo());
        limpiarErrores();
    }

    public void mostrarErrores(Map<String, String> erroresPaso) {
        limpiarErrores();
        vistas.get(indice).mostrarErrores(erroresPaso);
    }

    public void mostrarEstado(String texto, boolean ocupado) {
        String mensaje = texto == null ? "" : texto;
        estado.setText(mensaje);
        estado.setManaged(!mensaje.isBlank());
        estado.setVisible(!mensaje.isBlank());
        setDisable(ocupado);
        anterior.setDisable(ocupado || indice == 0);
        salir.setDisable(ocupado);
        siguiente.setDisable(ocupado);
        finalizar.setDisable(ocupado);
        finalizar.setText(ocupado ? "Guardando…" : "Guardar configuración");
    }

    public void actualizarRevision(FormularioAsistente formulario) {
        vistas.stream()
                .filter(VistaPasoRevision.class::isInstance)
                .map(VistaPasoRevision.class::cast)
                .findFirst()
                .ifPresent(vista -> vista.actualizarRevision(formulario));
    }

    public void limpiarContrasenas() {
        vistas.forEach(VistaPasoAsistente::limpiarContrasenas);
    }

    private void construirMarco() {
        BorderPane marco = VistaComun.crearMarco("");
        marco.setPadding(new Insets(8, 12, 8, 12));
        if (marco.getTop() instanceof VBox encabezadoAplicacion) {
            encabezadoAplicacion.setSpacing(3);
            encabezadoAplicacion.setPadding(new Insets(0, 0, 6, 0));
        }
        subtituloPaso.getStyleClass().add("text-muted");
        subtituloPaso.setWrapText(true);
        progreso.setPrefHeight(4);
        progreso.setMaxWidth(Double.MAX_VALUE);
        progreso.getStyleClass().add("progreso-asistente");
        VBox encabezado = new VBox(5, subtituloPaso, progreso);
        VBox tarjeta = VistaComun.crearTarjeta();
        tarjeta.setMaxWidth(960);
        tarjeta.setSpacing(8);
        tarjeta.setPadding(new Insets(12));
        tarjeta.getChildren().addAll(encabezado, estado, notaTransferencia);
        estado.setMinHeight(16);
        tarjeta.getChildren().add(areaPaso);
        VBox.setVgrow(areaPaso, Priority.ALWAYS);
        StackPane contenidoTarjeta = new StackPane(tarjeta);
        contenidoTarjeta.setAlignment(Pos.TOP_CENTER);
        ScrollPane desplazamiento = new ScrollPane(contenidoTarjeta);
        desplazamiento.setFitToWidth(true);
        desplazamiento.setHbarPolicy(ScrollPane.ScrollBarPolicy.NEVER);
        desplazamiento.getStyleClass().add("desplazamiento");
        marco.setCenter(desplazamiento);

        finalizar.getStyleClass().add("accent");
        finalizar.setOnAction(evento -> alFinalizar.run());
        anterior.setOnAction(evento -> alAnterior.run());
        siguiente.getStyleClass().add("accent");
        siguiente.setOnAction(evento -> alSiguiente.run());
        salir.getStyleClass().add("flat");
        salir.setOnAction(evento -> alSalir.run());
        HBox acciones = new HBox(6, salir, VistaComun.separadorFlexible(), anterior, siguiente, finalizar);
        acciones.setAlignment(Pos.CENTER_RIGHT);
        acciones.setPadding(new Insets(8, 0, 0, 0));
        marco.setBottom(acciones);

        setTop(marco.getTop());
        setCenter(marco.getCenter());
        setBottom(marco.getBottom());
        setPadding(marco.getPadding());
        getStyleClass().addAll("fondo-aplicacion", "asistente-propietario");
    }

    private void limpiarErrores() {
        vistas.forEach(VistaPasoAsistente::limpiarErrores);
        estado.setText("");
        estado.setVisible(false);
        estado.setManaged(false);
    }

    private void ocultarSugerenciasZonaHoraria() {
        vistas.stream()
                .filter(VistaPasoHorario.class::isInstance)
                .map(VistaPasoHorario.class::cast)
                .forEach(VistaPasoHorario::ocultarSugerencias);
    }

    private void actualizarIndicadorAdministrativo() {
        VistaPasoAcceso acceso = vistas.stream()
                .filter(VistaPasoAcceso.class::isInstance)
                .map(VistaPasoAcceso.class::cast)
                .findFirst()
                .orElseThrow();
        VistaPasoAdministrativa administrativa = vistas.stream()
                .filter(VistaPasoAdministrativa.class::isInstance)
                .map(VistaPasoAdministrativa.class::cast)
                .findFirst()
                .orElseThrow();
        administrativa.establecerContrasenaAcceso(acceso.copiarContrasenaActual());
    }
}
