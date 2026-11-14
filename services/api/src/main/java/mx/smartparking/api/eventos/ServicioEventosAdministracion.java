package mx.smartparking.api.eventos;

import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.function.LongSupplier;
import java.util.function.Supplier;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/** Envía avisos a las pantallas del personal autorizado cuando necesitan actualizar sus datos. */
@Component
public final class ServicioEventosAdministracion {

    static final long INTERVALO_HEARTBEAT_NANOS = TimeUnit.SECONDS.toNanos(10);
    static final long DURACION_CONCESION_NANOS = TimeUnit.SECONDS.toNanos(25);
    static final long INTERVALO_REVISION_MS = TimeUnit.SECONDS.toMillis(1);
    private static final long INTERVALO_VALIDACION_SESION_MS = TimeUnit.SECONDS.toMillis(25);
    static final long DURACION_EMISOR_MS = TimeUnit.MINUTES.toMillis(15);
    private static final int MAXIMO_SUSCRIPCIONES = 50;
    private static final int MAXIMO_POR_SESION = 5;
    private static final int MAXIMO_PENDIENTES = RegistroEventosAdministracion.CAPACIDAD_HISTORIAL;
    private static final Set<String> EVENTOS_VISIBLES_OPERADOR = Set.of(
            RegistroEventosAdministracion.NOMBRE_EVENTO_VISION_ACTUALIZADA,
            RegistroEventosAdministracion.NOMBRE_EVENTO_ACCESO_HISTORIAL_ACTUALIZADO,
            RegistroEventosAdministracion.NOMBRE_EVENTO_CLIENTE_REGISTRADO,
            RegistroEventosAdministracion.NOMBRE_EVENTO_MEMBRESIA_ACTUALIZADA,
            RegistroEventosAdministracion.NOMBRE_EVENTO_CAPTURA_RFID1_ACTUALIZADA,
            RegistroEventosAdministracion.NOMBRE_EVENTO_TARJETAS_RFID1_ACTUALIZADAS,
            RegistroEventosAdministracion.NOMBRE_EVENTO_RESINCRONIZAR);

    private final ValidadorSesionAdministracion validadorSesiones;
    private final RegistroEventosAdministracion registro = new RegistroEventosAdministracion();
    private final Object candadoRegistro = new Object();
    private final Object candadoPublicacion = new Object();
    private final Map<String, Set<SuscripcionEventosAdministracion>> suscripcionesPorSesion = new HashMap<>();
    private final ScheduledExecutorService ejecutorHeartbeat;
    private final LongSupplier relojNanos;
    private final Supplier<UUID> generadorSuscripcion;
    private int cantidadSuscripciones;
    private boolean cerrado;

    @Autowired
    public ServicioEventosAdministracion(
            GestorSesionesPropietario gestorSesiones,
            RepositorioCuentas repositorioCuentas) {
        this(gestorSesiones, repositorioCuentas, System::nanoTime, UUID::randomUUID, crearEjecutorHeartbeat());
    }

    ServicioEventosAdministracion(
            GestorSesionesPropietario gestorSesiones,
            RepositorioCuentas repositorioCuentas,
            LongSupplier relojNanos,
            Supplier<UUID> generadorSuscripcion,
            ScheduledExecutorService ejecutorHeartbeat) {
        this.validadorSesiones = new ValidadorSesionAdministracion(gestorSesiones, repositorioCuentas);
        this.relojNanos = relojNanos;
        this.generadorSuscripcion = generadorSuscripcion;
        this.ejecutorHeartbeat = ejecutorHeartbeat;
        ejecutorHeartbeat.scheduleAtFixedRate(
                this::comprobarConcesiones, INTERVALO_REVISION_MS, INTERVALO_REVISION_MS, TimeUnit.MILLISECONDS);
        ejecutorHeartbeat.scheduleAtFixedRate(
                this::comprobarVigenciaSesiones,
                INTERVALO_VALIDACION_SESION_MS,
                INTERVALO_VALIDACION_SESION_MS,
                TimeUnit.MILLISECONDS);
    }

    private static ScheduledExecutorService crearEjecutorHeartbeat() {
        return Executors.newSingleThreadScheduledExecutor(tarea -> {
            Thread hilo = new Thread(tarea, "smartparking-eventos-administracion");
            hilo.setDaemon(true);
            return hilo;
        });
    }

    /** Entrega la referencia que permite reconocer si el directorio cambió después de consultarlo. */
    public String cursorActual() {
        synchronized (candadoRegistro) {
            return registro.cursorActual();
        }
    }

    /** Registra un aviso para actualizar el directorio después de guardar el cambio. */
    public void publicarDirectorioActualizado() {
        publicarDirectorioActualizado(RegistroEventosAdministracion.NOMBRE_EVENTO_EMPLEADOS);
    }
    public void publicarDirectorioOperadorActualizado() {
        publicarDirectorioActualizado(RegistroEventosAdministracion.NOMBRE_EVENTO_OPERADORES);
    }

    /** Avisa a la persona autorizada que vuelva a consultar el estado de la lectura de su tarjeta. */
    public void publicarCapturaRfid1Actualizada() {
        publicarDirectorioActualizado(RegistroEventosAdministracion.NOMBRE_EVENTO_CAPTURA_RFID1_ACTUALIZADA);
    }

    /** Avisa que debe actualizarse la lista de tarjetas sin enviar números de tarjeta ni datos personales. */
    public void publicarTarjetasRfid1Actualizadas() {
        publicarDirectorioActualizado(RegistroEventosAdministracion.NOMBRE_EVENTO_TARJETAS_RFID1_ACTUALIZADAS);
    }

    /** Avisa que debe actualizarse el historial sin incluir datos personales. */
    public void publicarAccesoHistorialActualizado() {
        publicarDirectorioActualizado(RegistroEventosAdministracion.NOMBRE_EVENTO_ACCESO_HISTORIAL_ACTUALIZADO);
    }

    /** Avisa que debe volver a consultarse la ocupación observada por la cámara, sin incluir sus datos. */
    public void publicarVisionActualizada() {
        publicarDirectorioActualizado(RegistroEventosAdministracion.NOMBRE_EVENTO_VISION_ACTUALIZADA);
    }

    void publicarDirectorioActualizado(String nombreEvento) {
        synchronized (candadoPublicacion) {
            RegistroEventosAdministracion.Evento evento;
            List<SuscripcionEventosAdministracion> destinos;
            synchronized (candadoRegistro) {
                if (cerrado) {
                    return;
                }
                evento = registro.registrarCambio(nombreEvento);
                destinos = copiarSuscripciones();
            }
            destinos.forEach(suscripcion -> enviarEvento(suscripcion, evento));
        }
    }

    /** Empieza a enviar avisos continuos a la pantalla vinculada con la sesión autorizada. */
    public SseEmitter abrirStream(
            String idSesion,
            PrincipalPropietario principal,
            String cursorSolicitado) {
        validadorSesiones.exigirPropietario(principal);
        if (!validadorSesiones.esVigente(idSesion, principal)) {
            throw new ErrorConfiguracion(
                    HttpStatus.UNAUTHORIZED, "Tu acceso venció. Inicia sesión de nuevo.", "SESION_NO_VIGENTE");
        }

        PrincipalPropietario identidadStream = new PrincipalPropietario(
                principal.cuentaId(),
                principal.rol(),
                principal.revisionAcceso(),
                principal.revisionPropietario(),
                "");

        SuscripcionEventosAdministracion suscripcion;
        RegistroEventosAdministracion.PlanReproduccion plan;
        synchronized (candadoRegistro) {
            if (cerrado) {
                throw new ErrorConfiguracion(
                        HttpStatus.SERVICE_UNAVAILABLE,
                        "Las actualizaciones no están disponibles ahora.",
                        "SERVICIO_NO_DISPONIBLE");
            }
            Set<SuscripcionEventosAdministracion> sesiones = suscripcionesPorSesion.get(idSesion);
            if (cantidadSuscripciones >= MAXIMO_SUSCRIPCIONES
                    || (sesiones != null && sesiones.size() >= MAXIMO_POR_SESION)) {
                throw new ErrorConfiguracion(
                        HttpStatus.TOO_MANY_REQUESTS,
                        "No se pudo actualizar la información automáticamente. Recarga la pantalla para ver los cambios.",
                        "LIMITE_STREAMS_ALCANZADO");
            }

            plan = registro.resolver(cursorSolicitado);
            suscripcion = new SuscripcionEventosAdministracion(
                    idSesion, identidadStream, new SseEmitter(DURACION_EMISOR_MS),
                    generadorSuscripcion.get(), relojNanos.getAsLong());
            suscripcion.ultimaSecuenciaEnviada = plan.ultimaSecuenciaInicial();
            suscripcionesPorSesion.computeIfAbsent(idSesion, ignorado -> new HashSet<>()).add(suscripcion);
            cantidadSuscripciones++;
        }

        prepararEmisor(suscripcion);
        enviarEstadoInicial(suscripcion, plan);
        enviarHeartbeat(suscripcion);
        return suscripcion.emisor;
    }

    private void prepararEmisor(SuscripcionEventosAdministracion suscripcion) {
        suscripcion.emisor.onCompletion(() -> retirar(suscripcion));
        suscripcion.emisor.onTimeout(() -> retirar(suscripcion));
        suscripcion.emisor.onError(ignorado -> retirar(suscripcion));
    }

    private void enviarEstadoInicial(
            SuscripcionEventosAdministracion suscripcion,
            RegistroEventosAdministracion.PlanReproduccion plan) {
        synchronized (suscripcion.candadoEntrega) {
            if (suscripcion.cerrada) {
                return;
            }
            if (plan.requiereResincronizacion()) {
                enviarEventoBloqueado(
                        suscripcion,
                        registro.invalidacionActual());
            } else {
                plan.eventos().forEach(evento -> enviarEventoBloqueado(suscripcion, evento));
            }

            if (suscripcion.resincronizacionPendiente && !suscripcion.cerrada) {
                RegistroEventosAdministracion.Evento actual;
                synchronized (candadoRegistro) {
                    actual = registro.invalidacionActual();
                }
                suscripcion.eventosPendientes.clear();
                enviarEventoBloqueado(suscripcion, actual);
            } else {
                suscripcion.eventosPendientes.values().forEach(evento -> enviarEventoBloqueado(suscripcion, evento));
                suscripcion.eventosPendientes.clear();
            }
            suscripcion.inicializada = true;
        }
    }

    private void enviarEvento(
            SuscripcionEventosAdministracion suscripcion,
            RegistroEventosAdministracion.Evento evento) {
        synchronized (suscripcion.candadoEntrega) {
            if (suscripcion.cerrada || evento.secuencia() <= suscripcion.ultimaSecuenciaEnviada) {
                return;
            }
            if (!suscripcion.inicializada) {
                if (suscripcion.eventosPendientes.size() >= MAXIMO_PENDIENTES) {
                    suscripcion.eventosPendientes.clear();
                    suscripcion.resincronizacionPendiente = true;
                } else if (!suscripcion.resincronizacionPendiente) {
                    suscripcion.eventosPendientes.put(evento.secuencia(), evento);
                }
                return;
            }
            enviarEventoBloqueado(suscripcion, evento);
        }
    }

    private void enviarEventoBloqueado(
            SuscripcionEventosAdministracion suscripcion,
            RegistroEventosAdministracion.Evento evento) {
        if (suscripcion.cerrada || evento.secuencia() <= suscripcion.ultimaSecuenciaEnviada) {
            return;
        }
        boolean vigente;
        try {
            vigente = validadorSesiones.esVigente(suscripcion.idSesion, suscripcion.principal);
        } catch (RuntimeException excepcion) {
            // Si no se puede comprobar el acceso, la pantalla debe conectarse y consultar de nuevo.
            cerrar(suscripcion);
            return;
        }
        if (!vigente) {
            cerrar(suscripcion);
            return;
        }

        RegistroEventosAdministracion.Evento eventoVisible = filtrarEvento(suscripcion.principal, evento);
        try {
            suscripcion.emisor.send(SseEmitter.event()
                    .name(eventoVisible.nombreEvento())
                    .id(eventoVisible.cursor())
                    .data("{}", MediaType.APPLICATION_JSON));
            suscripcion.ultimaSecuenciaEnviada = evento.secuencia();
        } catch (IOException | RuntimeException excepcion) {
            // El servidor termina el envío de avisos cuando detecta que la pantalla se desconectó.
            retirar(suscripcion);
        }
    }

    private static RegistroEventosAdministracion.Evento filtrarEvento(
            PrincipalPropietario principal,
            RegistroEventosAdministracion.Evento evento) {
        if (principal.rol() == RolCuenta.DUENO
                || EVENTOS_VISIBLES_OPERADOR.contains(evento.nombreEvento())) {
            return evento;
        }
        return new RegistroEventosAdministracion.Evento(
                evento.secuencia(), evento.cursor(), RegistroEventosAdministracion.NOMBRE_EVENTO_RESINCRONIZAR);
    }

    void comprobarConcesiones() {
        List<SuscripcionEventosAdministracion> suscripciones;
        synchronized (candadoRegistro) {
            suscripciones = copiarSuscripciones();
        }
        for (SuscripcionEventosAdministracion suscripcion : suscripciones) {
            long ahora = relojNanos.getAsLong();
            boolean vencida;
            boolean enviarHeartbeat;
            synchronized (suscripcion.candadoEntrega) {
                vencida = !suscripcion.cerrada
                        && suscripcion.concesionVencida(ahora, DURACION_CONCESION_NANOS);
                enviarHeartbeat = !suscripcion.cerrada && !vencida
                        && suscripcion.heartbeatPendiente(ahora, INTERVALO_HEARTBEAT_NANOS);
            }
            if (vencida) {
                cerrar(suscripcion);
            } else if (enviarHeartbeat) {
                enviarHeartbeat(suscripcion);
            }
        }
    }

    void comprobarVigenciaSesiones() {
        List<SuscripcionEventosAdministracion> suscripciones;
        synchronized (candadoRegistro) {
            suscripciones = copiarSuscripciones();
        }
        for (SuscripcionEventosAdministracion suscripcion : suscripciones) {
            if (!validadorSesiones.esVigente(suscripcion.idSesion, suscripcion.principal)) {
                cerrar(suscripcion);
            }
        }
    }

    private void enviarHeartbeat(SuscripcionEventosAdministracion suscripcion) {
        if (!suscripcion.enviarHeartbeat(relojNanos.getAsLong())) {
            retirar(suscripcion);
        }
    }

    /** Renueva el permiso para seguir enviando avisos a la pantalla de esa sesión. */
    void confirmarHeartbeat(
            String idSesion,
            PrincipalPropietario principal,
            String suscripcionId,
            long secuencia) {
        if (secuencia < 1 || suscripcionId == null || !validadorSesiones.esVigente(idSesion, principal)) {
            return;
        }
        UUID identificador;
        try {
            identificador = UUID.fromString(suscripcionId);
        } catch (IllegalArgumentException excepcion) {
            return;
        }

        List<SuscripcionEventosAdministracion> suscripciones;
        synchronized (candadoRegistro) {
            Set<SuscripcionEventosAdministracion> registradas = suscripcionesPorSesion.get(idSesion);
            if (registradas == null) {
                return;
            }
            suscripciones = new ArrayList<>(registradas);
        }
        long ahora = relojNanos.getAsLong();
        for (SuscripcionEventosAdministracion suscripcion : suscripciones) {
            if (!suscripcion.id.equals(identificador)) {
                continue;
            }
            suscripcion.confirmarHeartbeat(secuencia, ahora, DURACION_CONCESION_NANOS);
            return;
        }
    }

    private List<SuscripcionEventosAdministracion> copiarSuscripciones() {
        List<SuscripcionEventosAdministracion> copia = new ArrayList<>(cantidadSuscripciones);
        suscripcionesPorSesion.values().forEach(copia::addAll);
        return copia;
    }

    private void cerrar(SuscripcionEventosAdministracion suscripcion) {
        if (!marcarCerrada(suscripcion)) {
            return;
        }
        retirarDelRegistro(suscripcion);
        try {
            suscripcion.emisor.complete();
        } catch (IllegalStateException ignorada) {
            // La comunicación pudo terminar porque se agotó el tiempo de espera o se perdió la conexión.
        }
    }

    private void retirar(SuscripcionEventosAdministracion suscripcion) {
        if (marcarCerrada(suscripcion)) {
            retirarDelRegistro(suscripcion);
        }
    }

    private boolean marcarCerrada(SuscripcionEventosAdministracion suscripcion) {
        synchronized (suscripcion.candadoEntrega) {
            if (suscripcion.cerrada) {
                return false;
            }
            suscripcion.cerrada = true;
            return true;
        }
    }

    private void retirarDelRegistro(SuscripcionEventosAdministracion suscripcion) {
        synchronized (candadoRegistro) {
            Set<SuscripcionEventosAdministracion> sesiones = suscripcionesPorSesion.get(suscripcion.idSesion);
            if (sesiones != null && sesiones.remove(suscripcion)) {
                cantidadSuscripciones--;
                if (sesiones.isEmpty()) {
                    suscripcionesPorSesion.remove(suscripcion.idSesion);
                }
            }
        }
    }

    @PreDestroy
    public void detener() {
        List<SuscripcionEventosAdministracion> suscripciones;
        synchronized (candadoRegistro) {
            cerrado = true;
            suscripciones = copiarSuscripciones();
        }
        ejecutorHeartbeat.shutdownNow();
        suscripciones.forEach(this::cerrar);
    }

}
