package mx.smartparking.api.clientes.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.clientes.configuracion.CatalogoMembresia;
import mx.smartparking.api.clientes.modelo.EstadoMembresia;
import mx.smartparking.api.clientes.modelo.PortalCliente;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.eventos.PublicadorEventosClientes;
import mx.smartparking.api.persistencia.CuentaPersistida;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import mx.smartparking.api.persistencia.membresia.RepositorioMembresias;
import mx.smartparking.api.persistencia.membresia.ResumenMembresiaPersistido;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

class ServicioClientesTest {

    private static final CatalogoMembresia CATALOGO = new CatalogoMembresia(
            "prod_VTMowkF8XuDWIR", "price_1USQ5HAqtHmR2qmyAWwUp5vy",
            "Smart Parking - Membresía Mensual", 39_900, "MXN", "month", 1);

    @Test
    void registraCuentaActivaConCorreoCanonicoYContrasenaExacta() {
        RepositorioCuentas cuentas = mock(RepositorioCuentas.class);
        PasswordEncoder codificador = mock(PasswordEncoder.class);
        ServicioClientes servicio = servicio(cuentas, codificador);
        UUID id = UUID.randomUUID();
        String contrasena = " Clave segura 10 🔒 ";
        when(codificador.encode(contrasena)).thenReturn("hash-persistido");
        when(cuentas.crearCliente("Ana María", "López", null, "ana@example.test", "hash-persistido"))
                .thenReturn(id);

        UUID resultado = servicio.registrarCliente(
                " Ana María ", " López ", "  ", " ANA@Example.Test ", contrasena);

        assertEquals(id, resultado);
        verify(codificador).encode(contrasena);
        verify(cuentas).crearCliente("Ana María", "López", null, "ana@example.test", "hash-persistido");
    }

    @Test
    void publicaRegistroDespuesDelCommit() {
        RepositorioCuentas cuentas = mock(RepositorioCuentas.class);
        PasswordEncoder codificador = mock(PasswordEncoder.class);
        PublicadorEventosClientes publicador = mock(PublicadorEventosClientes.class);
        UUID id = UUID.randomUUID();
        when(codificador.encode("Clave segura 10")).thenReturn("hash-persistido");
        when(cuentas.crearCliente("Ana", "López", null, "ana@example.test", "hash-persistido"))
                .thenReturn(id);
        TransactionSynchronizationManager.initSynchronization();
        try {
            servicio(cuentas, mock(RepositorioMembresias.class), codificador, publicador)
                    .registrarCliente("Ana", "López", null, "ana@example.test", "Clave segura 10");

            verify(publicador, never()).clienteRegistrado();
            TransactionSynchronizationManager.getSynchronizations()
                    .forEach(TransactionSynchronization::afterCommit);
            verify(publicador).clienteRegistrado();
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
        }
    }

    @Test
    void registroFallidoNoPublicaEvento() {
        RepositorioCuentas cuentas = mock(RepositorioCuentas.class);
        PasswordEncoder codificador = mock(PasswordEncoder.class);
        PublicadorEventosClientes publicador = mock(PublicadorEventosClientes.class);
        when(codificador.encode("Clave segura 10")).thenReturn("hash-persistido");
        when(cuentas.crearCliente(anyString(), anyString(), eq(null), anyString(), anyString()))
                .thenThrow(new IllegalStateException("fallo de prueba"));

        assertThrows(IllegalStateException.class,
                () -> servicio(cuentas, mock(RepositorioMembresias.class), codificador, publicador)
                        .registrarCliente("Ana", "López", null, "ana@example.test", "Clave segura 10"));

        verify(publicador, never()).clienteRegistrado();
    }

    @Test
    void portalMuestraSoloPerfilPropioYSinMembresia() {
        RepositorioCuentas cuentas = mock(RepositorioCuentas.class);
        RepositorioMembresias membresias = mock(RepositorioMembresias.class);
        UUID id = UUID.randomUUID();
        when(cuentas.obtener(id)).thenReturn(Optional.of(cuentaCliente(id, 3, "hash-acceso")));
        when(membresias.consultarResumenMembresia(id)).thenReturn(new ResumenMembresiaPersistido(
                "SIN_MEMBRESIA", null, null, null, false, true, null, null, null));

        PortalCliente portal = servicio(cuentas, membresias, mock(PasswordEncoder.class)).consultarPortal(id);

        assertEquals(id, portal.cliente().clienteId());
        assertEquals("ana@example.test", portal.cliente().correo());
        assertEquals(EstadoMembresia.SIN_MEMBRESIA, portal.membresia().estado());
        assertEquals(39_900, portal.membresia().plan().importeMenorUnidad());
        assertEquals("month", portal.membresia().plan().intervalo());
    }

    @Test
    void portalNoEntregaCuentasDeOtrosRoles() {
        RepositorioCuentas cuentas = mock(RepositorioCuentas.class);
        UUID id = UUID.randomUUID();
        when(cuentas.obtener(id)).thenReturn(Optional.of(new CuentaPersistida(
                id, "Ana", "López", null, "ana@example.test", "ana@example.test",
                RolCuenta.DUENO, true, "hash", 1)));

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio(cuentas, mock(PasswordEncoder.class)).consultarPortal(id));

        assertEquals(HttpStatus.NOT_FOUND, error.estadoHttp());
        assertEquals("CLIENTE_NO_ENCONTRADO", error.codigo());
    }

    @Test
    void cambioVerificaContrasenaYActualizaHashConRevisionEsperada() {
        RepositorioCuentas cuentas = mock(RepositorioCuentas.class);
        PasswordEncoder codificador = mock(PasswordEncoder.class);
        UUID id = UUID.randomUUID();
        String nueva = "Nueva clave segura 10";
        when(cuentas.obtener(id)).thenReturn(Optional.of(cuentaCliente(id, 8, "hash-actual")));
        when(codificador.matches("actual segura", "hash-actual")).thenReturn(true);
        when(codificador.encode(nueva)).thenReturn("hash-nuevo");
        when(cuentas.actualizarContrasenaCliente(id, 8, "hash-nuevo")).thenReturn(true);

        servicio(cuentas, codificador).cambiarContrasena(id, "actual segura", nueva);

        verify(codificador).matches("actual segura", "hash-actual");
        verify(cuentas).actualizarContrasenaCliente(id, 8, "hash-nuevo");
    }

    @Test
    void cambioRechazaContrasenaActualIncorrectaSinRotarAcceso() {
        RepositorioCuentas cuentas = mock(RepositorioCuentas.class);
        PasswordEncoder codificador = mock(PasswordEncoder.class);
        UUID id = UUID.randomUUID();
        when(cuentas.obtener(id)).thenReturn(Optional.of(cuentaCliente(id, 8, "hash-actual")));
        when(codificador.matches("incorrecta", "hash-actual")).thenReturn(false);

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio(cuentas, codificador).cambiarContrasena(id, "incorrecta", "Nueva clave segura"));

        assertEquals(HttpStatus.UNAUTHORIZED, error.estadoHttp());
        verify(cuentas, never()).actualizarContrasenaCliente(eq(id), eq(8L), anyString());
    }

    @Test
    void cambioCuentaPuntosUnicodeEnLugarDeUnidadesUtf16() {
        RepositorioCuentas cuentas = mock(RepositorioCuentas.class);
        PasswordEncoder codificador = mock(PasswordEncoder.class);
        UUID id = UUID.randomUUID();
        when(cuentas.obtener(id)).thenReturn(Optional.of(cuentaCliente(id, 8, "hash-actual")));
        when(codificador.matches("actual segura", "hash-actual")).thenReturn(true);

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio(cuentas, codificador).cambiarContrasena(id, "actual segura", "😀".repeat(9)));

        assertEquals("CONTRASENA_NO_VALIDA", error.codigo());
        verify(codificador, never()).encode(anyString());
        verify(cuentas, never()).actualizarContrasenaCliente(eq(id), eq(8L), anyString());
    }

    @Test
    void falloDeRevisionOptimistaSeInformaComoConflicto() {
        RepositorioCuentas cuentas = mock(RepositorioCuentas.class);
        PasswordEncoder codificador = mock(PasswordEncoder.class);
        UUID id = UUID.randomUUID();
        when(cuentas.obtener(id)).thenReturn(Optional.of(cuentaCliente(id, 8, "hash-actual")));
        when(codificador.matches("actual segura", "hash-actual")).thenReturn(true);
        when(codificador.encode("Nueva clave segura 10")).thenReturn("hash-nuevo");
        when(cuentas.actualizarContrasenaCliente(id, 8, "hash-nuevo")).thenReturn(false);

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio(cuentas, codificador).cambiarContrasena(id, "actual segura", "Nueva clave segura 10"));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertTrue(error.getMessage().contains("Inicia sesión"));
    }

    private static ServicioClientes servicio(RepositorioCuentas cuentas, PasswordEncoder codificador) {
        return servicio(cuentas, mock(RepositorioMembresias.class), codificador);
    }

    private static ServicioClientes servicio(
            RepositorioCuentas cuentas, RepositorioMembresias membresias, PasswordEncoder codificador) {
        return servicio(cuentas, membresias, codificador, mock(PublicadorEventosClientes.class));
    }

    private static ServicioClientes servicio(
            RepositorioCuentas cuentas,
            RepositorioMembresias membresias,
            PasswordEncoder codificador,
            PublicadorEventosClientes publicador) {
        return new ServicioClientes(cuentas, membresias, codificador, CATALOGO, publicador);
    }

    private static CuentaPersistida cuentaCliente(UUID id, long revision, String hash) {
        return new CuentaPersistida(id, "Ana", "López", null, "ana@example.test", "ana@example.test",
                RolCuenta.CLIENTE, true, hash, revision);
    }
}
