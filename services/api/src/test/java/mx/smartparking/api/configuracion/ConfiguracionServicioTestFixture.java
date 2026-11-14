package mx.smartparking.api.configuracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import mx.smartparking.api.correo.EstadoAviso;
import mx.smartparking.api.correo.NotificadorCorreo;
import mx.smartparking.api.persistencia.ConfiguracionPersistida;
import mx.smartparking.api.persistencia.RepositorioConfiguracion;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.transferencia.ProteccionIntentosTransferencia;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;

abstract class ConfiguracionServicioTestFixture {

    static final Instant AHORA = Instant.parse("2026-10-23T18:00:00Z");
    static final String CONTRASENA_ADMINISTRATIVA = "Administracion segura 2026";
    static final String CLAVE_IDEMPOTENCIA = "8c923790-714c-4f05-9e69-0b680d466913";

    RepositorioConfiguracion repositorio;
    RepositorioCuentas cuentas;
    PasswordEncoder codificador;
    GestorSesionesPropietario gestorSesiones;
    NotificadorCorreo notificador;
    ProteccionIntentosTransferencia proteccionIntentos;
    ConfiguracionServicio servicio;
    List<String> eventosTransaccion;

    @BeforeEach
    void preparar() {
        eventosTransaccion = new ArrayList<>();
        repositorio = mock(RepositorioConfiguracion.class);
        cuentas = mock(RepositorioCuentas.class);
        when(cuentas.crearDueno(any(), anyString())).thenReturn(UUID.randomUUID());
        codificador = mock(PasswordEncoder.class);
        gestorSesiones = mock(GestorSesionesPropietario.class);
        notificador = mock(NotificadorCorreo.class);
        proteccionIntentos = mock(ProteccionIntentosTransferencia.class);
        when(proteccionIntentos.permitido(any(), anyString())).thenReturn(true);
        servicio = new ConfiguracionServicio(
                repositorio,
                cuentas,
                codificador,
                notificador,
                administradorTransacciones(eventosTransaccion),
                new mx.smartparking.api.transferencia.ServicioTransferenciaPropietario(
                        repositorio, cuentas, codificador, gestorSesiones, notificador, proteccionIntentos,
                        administradorTransacciones(eventosTransaccion), Clock.fixed(AHORA, ZoneId.of("UTC")),
                        new SecureRandom()));
    }

    static ConfiguracionPersistida configuracionActiva() {
        return new ConfiguracionPersistida(
                EstadoConfiguracion.CONFIGURADA,
                5,
                9,
                UUID.randomUUID(),
                "Ana",
                "López",
                "García",
                "propietario@example.test",
                "hash-acceso-activo",
                "hash-admin-activo",
                "Centro",
                TipoEstacionamiento.PUBLICO,
                ModoHorario.INTERVALO_DIARIO,
                "America/Mexico_City",
                LocalTime.of(9, 0),
                LocalTime.of(17, 0),
                null,
                null,
                null,
                null,
                "NO_APLICA",
                "ENVIADO",
                UUID.randomUUID(),
                sha256("previous-idempotency-key"));
    }

    static ConfiguracionPersistida configuracionActivaSinPerfilLegado() {
        ConfiguracionPersistida actual = configuracionActiva();
        return new ConfiguracionPersistida(
                actual.estado(), actual.revision(), actual.revisionPropietario(), actual.estacionamientoId(),
                null, null, null, null, null, actual.hashContrasenaAdministrativa(),
                actual.nombreEstacionamiento(), actual.tipoEstacionamiento(), actual.modoHorario(),
                actual.zonaHoraria(), actual.horaApertura(), actual.horaCierre(), actual.transferId(),
                actual.hashGrantTransferencia(), actual.grantVenceEn(), actual.hashRecuperacionTransferencia(),
                actual.estadoAvisoTransferencia(), actual.estadoAvisoBienvenida(), actual.ultimaOperacionId(),
                actual.ultimaClaveIdempotenciaHash());
    }

    static ConfiguracionPersistida configuracionActivaConClave(
            ConfiguracionPersistida actual,
            String claveIdempotencia) {
        return new ConfiguracionPersistida(
                actual.estado(), actual.revision(), actual.revisionPropietario(), actual.estacionamientoId(),
                actual.propietarioNombres(), actual.propietarioPrimerApellido(), actual.propietarioSegundoApellido(),
                actual.correoPropietario(), actual.hashContrasenaAcceso(), actual.hashContrasenaAdministrativa(),
                actual.nombreEstacionamiento(), actual.tipoEstacionamiento(), actual.modoHorario(), actual.zonaHoraria(),
                actual.horaApertura(), actual.horaCierre(), actual.transferId(), actual.hashGrantTransferencia(),
                actual.grantVenceEn(), actual.hashRecuperacionTransferencia(), actual.estadoAvisoTransferencia(),
                actual.estadoAvisoBienvenida(), actual.ultimaOperacionId(), sha256(claveIdempotencia));
    }

    static ConfiguracionPersistida configuracionSinConfigurar() {
        return new ConfiguracionPersistida(
                EstadoConfiguracion.SIN_CONFIGURAR,
                0,
                0,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                "NO_APLICA",
                "NO_APLICA",
                null,
                null);
    }

    static SolicitudConfiguracion solicitudValida() {
        return new SolicitudConfiguracion(
                new SolicitudConfiguracion.PropietarioSolicitud(
                        "Ana", "López", "García", "ana@example.test",
                        "Acceso seguro 2026", "Administracion segura 2026"),
                new SolicitudConfiguracion.EstacionamientoSolicitud(
                        "Centro", TipoEstacionamiento.PUBLICO,
                        new SolicitudConfiguracion.HorarioSolicitud(
                                ModoHorario.INTERVALO_DIARIO,
                                "America/Mexico_City",
                                "09:00",
                                "17:00")));
    }

    static ConfiguracionPersistida configuracionPendiente(UUID transferId) {
        return configuracionPendiente(transferId, sha256("previous-grant"), AHORA.minusSeconds(3600));
    }

    static ConfiguracionPersistida configuracionPendiente(
            UUID transferId,
            String hashGrant,
            Instant venceEn) {
        ConfiguracionPersistida activa = configuracionActiva();
        return new ConfiguracionPersistida(
                EstadoConfiguracion.TRANSFERENCIA_PENDIENTE,
                12,
                10,
                activa.estacionamientoId(),
                null,
                null,
                null,
                null,
                null,
                null,
                activa.nombreEstacionamiento(),
                activa.tipoEstacionamiento(),
                activa.modoHorario(),
                activa.zonaHoraria(),
                activa.horaApertura(),
                activa.horaCierre(),
                transferId,
                hashGrant,
                venceEn,
                "hash-admin-recuperacion",
                "ENVIADO",
                "NO_APLICA",
                UUID.randomUUID(),
                sha256("previous-idempotency-key"));
    }

    static String sha256(String valor) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(valor.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception excepcion) {
            throw new IllegalStateException(excepcion);
        }
    }

    static PlatformTransactionManager administradorTransacciones(List<String> eventos) {
        return new PlatformTransactionManager() {
            @Override
            public TransactionStatus getTransaction(TransactionDefinition definicion) {
                eventos.add("inicio");
                return new SimpleTransactionStatus();
            }

            @Override
            public void commit(TransactionStatus estado) {
                eventos.add("commit");
            }

            @Override
            public void rollback(TransactionStatus estado) {
                eventos.add("rollback");
            }
        };
    }
}
