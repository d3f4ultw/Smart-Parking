package mx.smartparking.api.correo;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.net.ConnectException;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.mockito.ArgumentCaptor;
import mx.smartparking.api.configuracion.ConfiguracionServicio;
import mx.smartparking.api.configuracion.EstadoConfiguracion;
import mx.smartparking.api.configuracion.ModoHorario;
import mx.smartparking.api.configuracion.ResultadoConfiguracion;
import mx.smartparking.api.configuracion.SolicitudConfiguracion;
import mx.smartparking.api.configuracion.TipoEstacionamiento;
import mx.smartparking.api.persistencia.ConfiguracionPersistida;
import mx.smartparking.api.persistencia.RepositorioConfiguracion;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.persistencia.RepositorioConfiguracion.TipoAviso;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.transferencia.ProteccionIntentosTransferencia;
import org.junit.jupiter.api.Test;
import org.springframework.mail.MailSendException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;

class CorreoPostCommitTest {

    @Test
    void falloSmtpDespuesDelCommitConservaConfiguracionYNoRevierteLaTransaccion() {
        List<String> eventos = new ArrayList<>();
        RepositorioConfiguracion repositorio = mock(RepositorioConfiguracion.class);
        RepositorioCuentas cuentas = mock(RepositorioCuentas.class);
        when(cuentas.crearDueno(any(), anyString())).thenReturn(UUID.randomUUID());
        PasswordEncoder codificador = mock(PasswordEncoder.class);
        GestorSesionesPropietario gestorSesiones = mock(GestorSesionesPropietario.class);
        ProteccionIntentosTransferencia proteccionIntentos = mock(ProteccionIntentosTransferencia.class);
        JavaMailSender remitenteSmtp = mock(JavaMailSender.class);
        AdaptadorCorreoSmtp notificador = new AdaptadorCorreoSmtp(
                remitenteSmtp, true, "smartparking@example.test");
        ConfiguracionServicio servicio = new ConfiguracionServicio(
                repositorio,
                cuentas,
                codificador,
                notificador,
                administradorTransacciones(eventos),
                new mx.smartparking.api.transferencia.ServicioTransferenciaPropietario(
                        repositorio, cuentas, codificador, gestorSesiones, notificador, proteccionIntentos,
                        administradorTransacciones(eventos)));

        when(repositorio.bloquear()).thenAnswer(invocacion -> {
            eventos.add("bloquear");
            ConfiguracionPersistida actual = mock(ConfiguracionPersistida.class);
            when(actual.estado()).thenReturn(EstadoConfiguracion.SIN_CONFIGURAR);
            when(actual.revision()).thenReturn(0L);
            when(actual.revisionPropietario()).thenReturn(0L);
            return actual;
        });
        when(codificador.encode("Acceso seguro 2026")).thenReturn("hash-acceso");
        when(codificador.encode("Administracion segura 2026")).thenReturn("hash-administrativo");
        doAnswer(invocacion -> {
            eventos.add("configurar");
            return null;
        }).when(repositorio).configurarInicial(
                any(), anyString(), any(UUID.class), any(UUID.class), anyLong(), anyLong(), any(UUID.class), anyString());
        doAnswer(invocacion -> {
            eventos.add("smtp");
            throw new MailSendException("Se perdió la conexión con SMTP", new ConnectException("Connection refused"));
        }).when(remitenteSmtp).send(any(SimpleMailMessage.class));
        doAnswer(invocacion -> {
            eventos.add("guardar-aviso");
            return null;
        }).when(repositorio).actualizarEstadoAviso(
                any(UUID.class), eq(TipoAviso.BIENVENIDA), eq(EstadoAviso.FALLIDO.name()));

        ResultadoConfiguracion resultado = servicio.configurarInicial(solicitudValida(), "idempotencia-prueba-01");

        assertEquals(EstadoConfiguracion.CONFIGURADA, resultado.estado());
        assertEquals(EstadoAviso.FALLIDO, resultado.avisoBienvenida());
        assertEquals(List.of("inicio", "bloquear", "configurar", "commit", "smtp", "guardar-aviso"), eventos);
        ArgumentCaptor<SimpleMailMessage> capturador = ArgumentCaptor.forClass(SimpleMailMessage.class);
        verify(remitenteSmtp).send(capturador.capture());
        assertFalse(capturador.getValue().getText().contains("Acceso seguro 2026"));
        assertFalse(capturador.getValue().getText().contains("Administracion segura 2026"));
        verify(repositorio).actualizarEstadoAviso(
                any(UUID.class), eq(TipoAviso.BIENVENIDA), eq(EstadoAviso.FALLIDO.name()));
    }

    private static SolicitudConfiguracion solicitudValida() {
        return new SolicitudConfiguracion(
                new SolicitudConfiguracion.PropietarioSolicitud(
                        "Ana", "López", "García", "ana@example.test",
                        "Acceso seguro 2026", "Administracion segura 2026"),
                new SolicitudConfiguracion.EstacionamientoSolicitud(
                        "Centro", TipoEstacionamiento.PUBLICO,
                        new SolicitudConfiguracion.HorarioSolicitud(
                                ModoHorario.INTERVALO_DIARIO, "America/Mexico_City", "09:00", "17:00")));
    }

    private static PlatformTransactionManager administradorTransacciones(List<String> eventos) {
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
