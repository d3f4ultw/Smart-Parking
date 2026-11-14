package mx.smartparking.api.activacion;

import static org.mockito.Mockito.mock;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Set;
import java.util.UUID;
import mx.smartparking.api.correo.NotificadorInvitacionOperador;
import mx.smartparking.api.empleados.coordinacion.PuertoEmpleadosOperador;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.persistencia.CuentaActivacionOperador;
import mx.smartparking.api.persistencia.InvitacionOperadorPersistida;
import mx.smartparking.api.persistencia.RepositorioActivacionOperador;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;

/** Fixture compartido por las suites de ServicioActivacionOperadorTest. */
abstract class ServicioActivacionOperadorTestSupport {
     static final Instant AHORA = Instant.parse("2026-10-25T18:00:00Z");
     static final UUID OPERADOR_ID = UUID.fromString("b4d726d4-43c8-4a6e-9418-6d385cffdb6a");
     static final String TOKEN = "A".repeat(43);
     static final String TOKEN_HASH = SeguridadTokensOperador.hash(TOKEN);
     static final String ORIGEN = "https://parking.example.test";

     RepositorioActivacionOperador repositorio;
     NotificadorInvitacionOperador notificador;
     ServicioEventosAdministracion publicadorEventos;
     PasswordEncoder codificador;
     ProteccionIntentosActivacion proteccionIntentos;
     PuertoEmpleadosOperador empleados;
     ServicioActivacionOperador servicio;

    @BeforeEach
    void preparar() {
        repositorio = mock(RepositorioActivacionOperador.class);
        notificador = mock(NotificadorInvitacionOperador.class);
        publicadorEventos = mock(ServicioEventosAdministracion.class);
        codificador = mock(PasswordEncoder.class);
        proteccionIntentos = new ProteccionIntentosActivacion(Clock.fixed(AHORA, ZoneOffset.UTC));
        empleados = mock(PuertoEmpleadosOperador.class);
        servicio = new ServicioActivacionOperador(repositorio, notificador, codificador, proteccionIntentos,
                new AdministradorTransaccionesSimple(), ORIGEN, Clock.fixed(AHORA, ZoneOffset.UTC),
                new java.security.SecureRandom());
        servicio.establecerEventos(publicadorEventos);
        servicio.establecerEmpleados(empleados);
    }



     ServicioActivacionOperador servicioConOrigenYPerfiles(String origen, Set<String> perfiles) {
        return servicioConOrigenYPerfiles(origen, perfiles, false);
    }

     ServicioActivacionOperador servicioConOrigenYPerfiles(
            String origen, Set<String> perfiles, boolean permitirHttpLocal) {
        return new ServicioActivacionOperador(repositorio, notificador, codificador,
                new ProteccionIntentosActivacion(Clock.fixed(AHORA, ZoneOffset.UTC)),
                new AdministradorTransaccionesSimple(), origen, permitirHttpLocal, perfiles,
                Clock.fixed(AHORA, ZoneOffset.UTC), new java.security.SecureRandom());
    }

     static InvitacionOperadorPersistida invitacion(
            String tokenHash, Instant venceEn, Instant consumidoEn,
            EstadoEnvioInvitacion estado) {
        return new InvitacionOperadorPersistida(OPERADOR_ID, tokenHash, AHORA.minusSeconds(1), venceEn,
                consumidoEn, estado, AHORA.minusSeconds(1));
    }

     static CuentaActivacionOperador cuentaPendiente() {
        return new CuentaActivacionOperador(OPERADOR_ID, RolCuenta.OPERADOR, "PENDIENTE",
                "operador@example.test", null, 0);
    }

     static CuentaActivacionOperador cuentaPendiente(long empleadoId) {
        return new CuentaActivacionOperador(OPERADOR_ID, RolCuenta.OPERADOR, "PENDIENTE",
                "operador@example.test", null, 0, empleadoId);
    }

     static final class AdministradorTransaccionesSimple implements PlatformTransactionManager {

        @Override
        public TransactionStatus getTransaction(TransactionDefinition definicion) {
            return new SimpleTransactionStatus();
        }

        @Override
        public void commit(TransactionStatus estado) {
        }

        @Override
        public void rollback(TransactionStatus estado) {
        }
    }
}
