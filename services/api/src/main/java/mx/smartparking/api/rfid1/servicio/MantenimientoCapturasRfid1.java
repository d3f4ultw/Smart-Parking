package mx.smartparking.api.rfid1.servicio;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Set;
import mx.smartparking.api.eventos.PublicadorCapturaRfid1;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.SesionPropietarioRevocada;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Cierra lecturas vencidas o abandonadas y elimina, cuando corresponde, los registros antiguos ya
 * terminados.
 */
@Component
public class MantenimientoCapturasRfid1 {

    private static final Duration RETENCION_TERMINALES = Duration.ofHours(24);
    private final RepositorioRfid1 repositorio;
    private final GestorSesionesPropietario sesiones;
    private final TransactionTemplate transaccion;
    private final Clock reloj;
    private final PublicadorCapturaRfid1 publicador;

    @Autowired
    public MantenimientoCapturasRfid1(
            RepositorioRfid1 repositorio,
            GestorSesionesPropietario sesiones,
            PlatformTransactionManager administradorTransacciones,
            PublicadorCapturaRfid1 publicador) {
        this(repositorio, sesiones, administradorTransacciones, Clock.systemUTC(), publicador);
    }

    MantenimientoCapturasRfid1(
            RepositorioRfid1 repositorio,
            GestorSesionesPropietario sesiones,
            PlatformTransactionManager administradorTransacciones,
            Clock reloj,
            PublicadorCapturaRfid1 publicador) {
        this.repositorio = repositorio;
        this.sesiones = sesiones;
        this.transaccion = new TransactionTemplate(administradorTransacciones);
        this.reloj = reloj;
        this.publicador = publicador;
    }

    /** Cierra las lecturas cuyo tiempo terminó o cuya sesión ya no está activa. */
    @Scheduled(fixedDelayString = "${smartparking.rfid1.cleanup-delay-ms:15000}")
    public void limpiarPeriodicamente() {
        Instant limite = reloj.instant();
        Set<String> huellasActivas = sesiones.huellasSesionesActivas();
        boolean huboCambios = ejecutarLimpieza(huellasActivas, limite);
        publicador.publicarSiActualizada(huboCambios);
    }

    /** Cancela las lecturas pendientes cuando se retira el acceso de la sesión que las inició. */
    @EventListener
    public void invalidarSesionRevocada(SesionPropietarioRevocada evento) {
        Integer invalidadas = transaccion.execute(estado ->
                repositorio.invalidarPorSesion(evento.huellaSesion(), reloj.instant()));
        publicador.publicarSiActualizada(invalidadas != null && invalidadas > 0);
    }

    private boolean ejecutarLimpieza(Set<String> huellasActivas, Instant ahora) {
        Integer cambios = transaccion.execute(estado -> {
            int expiradas = repositorio.expirarCapturasVencidas(ahora);
            int sesionesAusentes = repositorio.invalidarSesionesAusentes(huellasActivas, ahora);
            repositorio.purgarCapturasTerminalesAnterioresA(ahora.minus(RETENCION_TERMINALES));
            return expiradas + sesionesAusentes;
        });
        return cambios != null && cambios > 0;
    }
}
