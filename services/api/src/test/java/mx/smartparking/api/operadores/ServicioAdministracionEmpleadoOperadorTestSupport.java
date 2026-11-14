package mx.smartparking.api.operadores;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.activacion.ServicioActivacionOperador;
import mx.smartparking.api.empleados.coordinacion.EmpleadoEnlaceOperador;
import mx.smartparking.api.empleados.coordinacion.PuertoEmpleadosOperador;
import mx.smartparking.api.eventos.ServicioEventosAdministracion;
import mx.smartparking.api.persistencia.RepositorioAccionesEmpleadoOperador;
import mx.smartparking.api.persistencia.RepositorioOperadores;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.BeforeEach;
import org.mockito.Mock;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;

/** Fixture compartido por las suites de ServicioAdministracionEmpleadoOperadorTest. */
abstract class ServicioAdministracionEmpleadoOperadorTestSupport {
     static final long EMPLEADO_ID = 42L;
     static final UUID DUENO_ID = UUID.fromString("85a4bff5-eae0-4ba7-b509-24f4071e05fa");
     static final UUID OPERADOR_ID = UUID.fromString("8c3d3c62-e588-48dc-96ec-6d9d98c70dcb");
     static final String CLAVE = "c0d0f0de-7641-4c78-b6a6-e26904c271e8";
     static final Instant CREADA = Instant.parse("2026-10-20T10:00:00Z");

    @Mock
    RepositorioOperadores operadores;
    @Mock
    RepositorioAccionesEmpleadoOperador acciones;
    @Mock
    PuertoInvitacionesAdministracion invitaciones;
    @Mock
    ServicioActivacionOperador activacion;
    @Mock
    PuertoEmpleadosOperador empleados;
    @Mock
    GestorSesionesPropietario sesiones;
    @Mock
    ServicioEventosAdministracion eventos;

     final List<String> orden = new ArrayList<>();
     boolean transaccionConfirmada;
     ServicioAdministracionEmpleadoOperador servicio;

    @BeforeEach
    void preparar() {
        servicio = new ServicioAdministracionEmpleadoOperador(operadores, acciones, invitaciones, activacion,
                empleados, sesiones, eventos, administradorTransacciones());
    }



     static String huella(String... campos) {
        try {
            java.security.MessageDigest digest = java.security.MessageDigest.getInstance("SHA-256");
            for (String campo : campos) {
                if (campo == null) {
                    digest.update(java.nio.ByteBuffer.allocate(Integer.BYTES).putInt(-1).array());
                } else {
                    byte[] valor = campo.getBytes(java.nio.charset.StandardCharsets.UTF_8);
                    digest.update(java.nio.ByteBuffer.allocate(Integer.BYTES).putInt(valor.length).array());
                    digest.update(valor);
                }
            }
            return java.util.HexFormat.of().formatHex(digest.digest());
        } catch (java.security.NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException(excepcion);
        }
    }

     static String huellaPromocion() {
        try {
            java.security.MessageDigest digest = java.security.MessageDigest.getInstance("SHA-256");
            for (String campo : List.of("PROMOVER", Long.toString(EMPLEADO_ID))) {
                byte[] valor = campo.getBytes(java.nio.charset.StandardCharsets.UTF_8);
                digest.update(java.nio.ByteBuffer.allocate(Integer.BYTES).putInt(valor.length).array());
                digest.update(valor);
            }
            return java.util.HexFormat.of().formatHex(digest.digest());
        } catch (java.security.NoSuchAlgorithmException excepcion) {
            throw new IllegalStateException(excepcion);
        }
    }

     void prepararConciliacion(
            EmpleadoEnlaceOperador empleado, CuentaOperadorAdministrable legada) {
        when(empleados.consultarPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(acciones.reservar(eq(DUENO_ID), anyString(), anyString(), eq("VINCULAR"), eq(EMPLEADO_ID)))
                .thenReturn(true);
        when(empleados.bloquearPorId(EMPLEADO_ID)).thenReturn(Optional.of(empleado));
        when(operadores.buscarCuentaVinculada(EMPLEADO_ID)).thenReturn(Optional.empty());
        when(operadores.bloquearCuentaAdministrable(OPERADOR_ID)).thenReturn(Optional.of(legada));
    }

     static EmpleadoEnlaceOperador empleado(String estado, long revision, String correo) {
        return new EmpleadoEnlaceOperador(EMPLEADO_ID, "E-0042", estado, revision, correo, correo);
    }

     static CuentaOperadorAdministrable cuenta(
            EstadoCuentaOperador estado, long revision, String correo, Long empleadoId) {
        return new CuentaOperadorAdministrable(OPERADOR_ID, "Ana", "López", null,
                correo, estado, CREADA, revision, empleadoId);
    }

     static PrincipalPropietario dueno() {
        return new PrincipalPropietario(DUENO_ID, RolCuenta.DUENO, 1, 1, "dueno@example.test");
    }

     PlatformTransactionManager administradorTransacciones() {
        return new PlatformTransactionManager() {
            @Override
            public TransactionStatus getTransaction(TransactionDefinition definicion) {
                transaccionConfirmada = false;
                orden.add("inicio");
                return new SimpleTransactionStatus();
            }

            @Override
            public void commit(TransactionStatus estado) {
                transaccionConfirmada = true;
                orden.add("commit");
            }

            @Override
            public void rollback(TransactionStatus estado) {
                orden.add("rollback");
            }
        };
    }
}
