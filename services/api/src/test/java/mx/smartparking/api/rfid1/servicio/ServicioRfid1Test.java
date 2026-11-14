package mx.smartparking.api.rfid1.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.configuracion.EstadoConfiguracion;
import mx.smartparking.api.configuracion.TipoEstacionamiento;
import mx.smartparking.api.eventos.PublicadorCapturaRfid1;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.CapturaRfid1Persistida;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.DestinoRfid1Persistido;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.NuevaCapturaRfid1;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.ResultadoEstadoCaptura;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.ResultadoLecturaRfid1;
import mx.smartparking.api.persistencia.ConfiguracionPersistida;
import mx.smartparking.api.persistencia.RepositorioConfiguracion;
import mx.smartparking.api.seguridad.PrincipalPropietario;
import mx.smartparking.api.seguridad.RolCuenta;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;

class ServicioRfid1Test {

    private static final Instant AHORA = Instant.parse("2026-10-27T22:00:00Z");
    private static final UUID DUENO_ID = UUID.fromString("16ea6042-2a9c-4f23-93a0-97c19a632863");
    private static final UUID CLIENTE_ID = UUID.fromString("ed8b4a88-7822-4bc7-b76f-351eef392de9");
    private static final String CAPTURA_ID = "00112233445566778899aabbccddeeff";
    private static final String CLAVE = "clave-idempotente-001";
    private static final String HUELLA_SESION = ClavesRfid1.hashClave("sesion-propietario-prueba");
    private static final PrincipalPropietario DUENO = new PrincipalPropietario(
            DUENO_ID, RolCuenta.DUENO, 4, 9, "dueno@example.test");

    @Test
    void creaCapturaDeDuracionAcotadaConIdPublicoYClaveHash() {
        RepositorioRfid1 repositorio = org.mockito.Mockito.mock(RepositorioRfid1.class);
        AdministradorTransaccionesFalso transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicador = org.mockito.Mockito.mock(PublicadorCapturaRfid1.class);
        doAnswer(invocacion -> {
            assertEquals(1, transacciones.confirmadas);
            return null;
        }).when(publicador).publicarSiActualizada(true);
        ServicioRfid1 servicio = servicio(repositorio, transacciones, publicador);
        when(repositorio.buscarPorIdempotencia(DUENO_ID, ClavesRfid1.hashClave(CLAVE), HUELLA_SESION))
                .thenReturn(Optional.empty());
        when(repositorio.buscarActivaDePropietario(DUENO_ID, 4, 9, HUELLA_SESION, AHORA))
                .thenReturn(Optional.empty());
        when(repositorio.resolverDestino("CLIENTE", "CLI-0001"))
                .thenReturn(Optional.of(new DestinoRfid1Persistido(
                        "CLIENTE", "CLI-0001", CLIENTE_ID, null, true, "ACTIVA")));
        when(repositorio.destinoTieneTarjeta(any(DestinoRfid1Persistido.class))).thenReturn(false);
        when(repositorio.insertarCaptura(any(NuevaCapturaRfid1.class))).thenReturn(true);

        var respuesta = servicio.crearCaptura("CLIENTE", "CLI-0001", CLAVE, HUELLA_SESION, DUENO);

        assertTrue(respuesta.capturaId().matches("[0-9a-f]{32}"));
        assertEquals("PENDIENTE", respuesta.estado());
        assertEquals(AHORA.plusSeconds(120), respuesta.expiraEn());
        assertEquals(1, transacciones.confirmadas);
        verify(publicador).publicarSiActualizada(true);
        verify(repositorio).expirarCapturasVencidas(AHORA);
        verify(repositorio).purgarCapturasTerminalesAnterioresA(AHORA.minusSeconds(24 * 60 * 60));
    }

    @Test
    void rechazaPersonaInactivaAntesDeRevisarTarjetas() {
        RepositorioRfid1 repositorio = org.mockito.Mockito.mock(RepositorioRfid1.class);
        var servicio = servicio(repositorio, new AdministradorTransaccionesFalso());
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0);
        when(repositorio.purgarCapturasTerminalesAnterioresA(AHORA.minusSeconds(24 * 60 * 60))).thenReturn(0);
        when(repositorio.buscarActivaParaDispositivo(AHORA)).thenReturn(Optional.empty());
        when(repositorio.buscarPorIdempotencia(DUENO_ID, ClavesRfid1.hashClave(CLAVE), HUELLA_SESION))
                .thenReturn(Optional.empty());
        when(repositorio.buscarActivaDePropietario(DUENO_ID, 4, 9, HUELLA_SESION, AHORA))
                .thenReturn(Optional.empty());
        when(repositorio.resolverDestino("CLIENTE", "CLI-0001"))
                .thenReturn(Optional.of(new DestinoRfid1Persistido("CLIENTE", "CLI-0001", CLIENTE_ID, null, false)));

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.crearCaptura("CLIENTE", "CLI-0001", CLAVE, HUELLA_SESION, DUENO));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertEquals("PERSONA_INACTIVA", error.codigo());
        verify(repositorio, never()).destinoTieneTarjeta(any(DestinoRfid1Persistido.class));
        verify(repositorio, never()).insertarCaptura(any(NuevaCapturaRfid1.class));
    }

    @Test
    void rechazaClienteSinMembresiaAntesDeRevisarTarjetas() {
        RepositorioRfid1 repositorio = org.mockito.Mockito.mock(RepositorioRfid1.class);
        var servicio = servicio(repositorio, new AdministradorTransaccionesFalso());
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0);
        when(repositorio.purgarCapturasTerminalesAnterioresA(AHORA.minusSeconds(24 * 60 * 60))).thenReturn(0);
        when(repositorio.buscarActivaParaDispositivo(AHORA)).thenReturn(Optional.empty());
        when(repositorio.buscarPorIdempotencia(DUENO_ID, ClavesRfid1.hashClave(CLAVE), HUELLA_SESION))
                .thenReturn(Optional.empty());
        when(repositorio.buscarActivaDePropietario(DUENO_ID, 4, 9, HUELLA_SESION, AHORA))
                .thenReturn(Optional.empty());
        when(repositorio.resolverDestino("CLIENTE", "CLI-0001"))
                .thenReturn(Optional.of(new DestinoRfid1Persistido(
                        "CLIENTE", "CLI-0001", CLIENTE_ID, null, true, "SIN_MEMBRESIA")));

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.crearCaptura("CLIENTE", "CLI-0001", CLAVE, HUELLA_SESION, DUENO));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertEquals("CLIENTE_SIN_MEMBRESIA", error.codigo());
        assertTrue(error.getMessage().contains("sin membresía"));
        verify(repositorio, never()).destinoTieneTarjeta(any(DestinoRfid1Persistido.class));
        verify(repositorio, never()).insertarCaptura(any(NuevaCapturaRfid1.class));
    }

    @Test
    void rechazaTipoQueNoCoincideConLaModalidadAntesDeResolverPersona() {
        RepositorioRfid1 repositorio = org.mockito.Mockito.mock(RepositorioRfid1.class);
        var servicio = servicio(repositorio, new AdministradorTransaccionesFalso(), TipoEstacionamiento.PRIVADO);
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0);
        when(repositorio.purgarCapturasTerminalesAnterioresA(AHORA.minusSeconds(24 * 60 * 60))).thenReturn(0);
        when(repositorio.buscarActivaParaDispositivo(AHORA)).thenReturn(Optional.empty());

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.crearCaptura("CLIENTE", "CLI-0001", CLAVE, HUELLA_SESION, DUENO));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertEquals("TIPO_ENTIDAD_NO_DISPONIBLE", error.codigo());
        verify(repositorio, never()).resolverDestino("CLIENTE", "CLI-0001");
    }

    @Test
    void capturaDeOperadorQuedaLigadaASuCuentaRevisionYHuellaDeSesion() {
        PrincipalPropietario operador = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.OPERADOR, 7, 0, "operador@example.test");
        RepositorioRfid1 repositorio = org.mockito.Mockito.mock(RepositorioRfid1.class);
        ServicioRfid1 servicio = servicio(repositorio, new AdministradorTransaccionesFalso());
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0);
        when(repositorio.buscarPorIdempotencia(operador.cuentaId(), ClavesRfid1.hashClave(CLAVE), HUELLA_SESION))
                .thenReturn(Optional.empty());
        when(repositorio.buscarActivaDePropietario(
                operador.cuentaId(), 7, 1, HUELLA_SESION, AHORA)).thenReturn(Optional.empty());
        when(repositorio.resolverDestino("CLIENTE", "CLI-0001"))
                .thenReturn(Optional.of(new DestinoRfid1Persistido(
                        "CLIENTE", "CLI-0001", CLIENTE_ID, null, true, "ACTIVA")));
        when(repositorio.destinoTieneTarjeta(any(DestinoRfid1Persistido.class))).thenReturn(false);
        when(repositorio.insertarCaptura(any(NuevaCapturaRfid1.class))).thenReturn(true);

        servicio.crearCaptura("CLIENTE", "CLI-0001", CLAVE, HUELLA_SESION, operador);

        org.mockito.ArgumentCaptor<NuevaCapturaRfid1> captura =
                org.mockito.ArgumentCaptor.forClass(NuevaCapturaRfid1.class);
        verify(repositorio).insertarCaptura(captura.capture());
        assertEquals(operador.cuentaId(), captura.getValue().propietarioId());
        assertEquals(7, captura.getValue().revisionAcceso());
        assertEquals(1, captura.getValue().revisionPropietario());
        assertEquals(HUELLA_SESION, captura.getValue().huellaSesion());
    }

    @Test
    void operadorReproduceLaCapturaIdempotenteConLaRevisionPersistida() {
        PrincipalPropietario operador = new PrincipalPropietario(
                UUID.randomUUID(), RolCuenta.OPERADOR, 7, 0, "operador@example.test");
        RepositorioRfid1 repositorio = org.mockito.Mockito.mock(RepositorioRfid1.class);
        ServicioRfid1 servicio = servicio(repositorio, new AdministradorTransaccionesFalso());
        String hashClave = ClavesRfid1.hashClave(CLAVE);
        String huella = ClavesRfid1.huellaSolicitud("CLIENTE", "CLI-0001");
        CapturaRfid1Persistida previa = new CapturaRfid1Persistida(
                CAPTURA_ID, "CLIENTE", "CLI-0001", CLIENTE_ID, null, operador.cuentaId(), 7, 1, HUELLA_SESION,
                hashClave, huella, null, null, "ESCANEANDO", null, null, AHORA, AHORA.plusSeconds(120), null,
                null, null, null, null, null);
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0);
        when(repositorio.buscarActivaParaDispositivo(AHORA)).thenReturn(Optional.empty());
        when(repositorio.buscarPorIdempotencia(operador.cuentaId(), hashClave, HUELLA_SESION))
                .thenReturn(Optional.of(previa));

        var repetida = servicio.crearCaptura("CLIENTE", "CLI-0001", CLAVE, HUELLA_SESION, operador);

        assertEquals(CAPTURA_ID, repetida.capturaId());
        assertEquals("ESCANEANDO", repetida.estado());
        verify(repositorio).buscarPorIdempotencia(operador.cuentaId(), hashClave, HUELLA_SESION);
        verify(repositorio, never()).insertarCaptura(any(NuevaCapturaRfid1.class));
    }

    @Test
    void mismaClaveYHuellaReproducenLaCapturaSinReservarOtra() {
        RepositorioRfid1 repositorio = org.mockito.Mockito.mock(RepositorioRfid1.class);
        ServicioRfid1 servicio = servicio(repositorio, new AdministradorTransaccionesFalso());
        String hashClave = ClavesRfid1.hashClave(CLAVE);
        String huella = ClavesRfid1.huellaSolicitud("CLIENTE", "CLI-0001");
        CapturaRfid1Persistida previa = new CapturaRfid1Persistida(
                CAPTURA_ID, "CLIENTE", "CLI-0001", CLIENTE_ID, null, DUENO_ID, 4, 9, HUELLA_SESION,
                hashClave, huella, null, null, "ESCANEANDO", null, null, AHORA, AHORA.plusSeconds(120), null,
                null, null, null, null, null);
        when(repositorio.buscarPorIdempotencia(DUENO_ID, hashClave, HUELLA_SESION)).thenReturn(Optional.of(previa));

        var repetida = servicio.crearCaptura("CLIENTE", "CLI-0001", CLAVE, HUELLA_SESION, DUENO);

        assertEquals(CAPTURA_ID, repetida.capturaId());
        assertEquals("ESCANEANDO", repetida.estado());
        verify(repositorio, never()).insertarCaptura(any(NuevaCapturaRfid1.class));
    }

    @Test
    void claveDeOtraSesionNoRevelaNiReproduceLaCapturaExistente() {
        RepositorioRfid1 repositorio = org.mockito.Mockito.mock(RepositorioRfid1.class);
        AdministradorTransaccionesFalso transacciones = new AdministradorTransaccionesFalso();
        ServicioRfid1 servicio = servicio(repositorio, transacciones);
        String hashClave = ClavesRfid1.hashClave(CLAVE);
        when(repositorio.buscarPorIdempotencia(DUENO_ID, hashClave, HUELLA_SESION))
                .thenReturn(Optional.empty(), Optional.empty());
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0);
        when(repositorio.purgarCapturasTerminalesAnterioresA(AHORA.minusSeconds(24 * 60 * 60))).thenReturn(0);
        when(repositorio.buscarActivaParaDispositivo(AHORA)).thenReturn(Optional.empty());
        when(repositorio.buscarActivaDePropietario(DUENO_ID, 4, 9, HUELLA_SESION, AHORA))
                .thenReturn(Optional.empty());
        when(repositorio.resolverDestino("CLIENTE", "CLI-0001"))
                .thenReturn(Optional.of(new DestinoRfid1Persistido("CLIENTE", "CLI-0001", CLIENTE_ID, null, true)));
        when(repositorio.destinoTieneTarjeta(any(DestinoRfid1Persistido.class))).thenReturn(false);
        when(repositorio.insertarCaptura(any(NuevaCapturaRfid1.class))).thenReturn(false);

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.crearCaptura("CLIENTE", "CLI-0001", CLAVE, HUELLA_SESION, DUENO));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertEquals("CAPTURA_EN_CURSO", error.codigo());
        verify(repositorio, org.mockito.Mockito.times(2))
                .buscarPorIdempotencia(DUENO_ID, hashClave, HUELLA_SESION);
        assertEquals(1, transacciones.revertidas);
    }

    @Test
    void replayDeLecturaNoPublicaUnaSegundaInvalidacion() {
        RepositorioRfid1 repositorio = org.mockito.Mockito.mock(RepositorioRfid1.class);
        AdministradorTransaccionesFalso transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicador = org.mockito.Mockito.mock(PublicadorCapturaRfid1.class);
        ServicioRfid1 servicio = servicio(repositorio, transacciones, publicador);
        String claveLectura = ClavesRfid1.uuidV5(CAPTURA_ID, "000A");
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0, 0);
        when(repositorio.completarLectura(
                CAPTURA_ID, "000A", "04A1B2C3", ClavesRfid1.huellaUid("04A1B2C3"), AHORA))
                .thenReturn(
                        new ResultadoLecturaRfid1("VISTA_PREVIA", "PREVIEW_READY", null, false),
                        new ResultadoLecturaRfid1("VISTA_PREVIA", "PREVIEW_READY", null, true));

        servicio.procesarLectura(CAPTURA_ID, "000A", "04A1B2C3", claveLectura);
        servicio.procesarLectura(CAPTURA_ID, "000A", "04A1B2C3", claveLectura);

        verify(publicador).publicarSiActualizada(true);
        verify(publicador).publicarSiActualizada(false);
        assertEquals(2, transacciones.confirmadas);
    }

    @Test
    void escaneoSoloInvalidaAlPasarDePendienteAEscaneando() {
        RepositorioRfid1 repositorio = org.mockito.Mockito.mock(RepositorioRfid1.class);
        AdministradorTransaccionesFalso transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicador = org.mockito.Mockito.mock(PublicadorCapturaRfid1.class);
        ServicioRfid1 servicio = servicio(repositorio, transacciones, publicador);
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0, 0);
        when(repositorio.buscarActivaParaDispositivo(AHORA)).thenReturn(
                Optional.of(captura("PENDIENTE")), Optional.of(captura("ESCANEANDO")));
        when(repositorio.marcarEscaneando(CAPTURA_ID, AHORA))
                .thenReturn(new ResultadoEstadoCaptura("ESCANEANDO", null));

        servicio.informarEscaneando(CAPTURA_ID);
        servicio.informarEscaneando(CAPTURA_ID);

        verify(publicador).publicarSiActualizada(true);
        verify(publicador).publicarSiActualizada(false);
        assertEquals(2, transacciones.confirmadas);
    }

    @Test
    void cancelacionRepetidaNoPublicaUnaSegundaInvalidacion() {
        RepositorioRfid1 repositorio = org.mockito.Mockito.mock(RepositorioRfid1.class);
        AdministradorTransaccionesFalso transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicador = org.mockito.Mockito.mock(PublicadorCapturaRfid1.class);
        ServicioRfid1 servicio = servicio(repositorio, transacciones, publicador);
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(0, 0);
        when(repositorio.buscarPorPropietario(CAPTURA_ID, DUENO_ID, 4, 9, HUELLA_SESION)).thenReturn(
                Optional.of(captura("PENDIENTE")), Optional.of(captura("CANCELADA")));
        when(repositorio.cancelar(CAPTURA_ID, DUENO_ID, 4, 9, HUELLA_SESION, AHORA))
                .thenReturn(new ResultadoEstadoCaptura("CANCELADA", null));

        servicio.cancelarCaptura(CAPTURA_ID, HUELLA_SESION, DUENO);
        servicio.cancelarCaptura(CAPTURA_ID, HUELLA_SESION, DUENO);

        verify(publicador).publicarSiActualizada(true);
        verify(publicador).publicarSiActualizada(false);
        assertEquals(2, transacciones.confirmadas);
    }

    @Test
    void publicaExpiracionSoloDespuesDeConfirmarLaConsulta() {
        RepositorioRfid1 repositorio = org.mockito.Mockito.mock(RepositorioRfid1.class);
        AdministradorTransaccionesFalso transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicador = org.mockito.Mockito.mock(PublicadorCapturaRfid1.class);
        doAnswer(invocacion -> {
            assertEquals(1, transacciones.confirmadas);
            return null;
        }).when(publicador).publicarSiActualizada(true);
        when(repositorio.expirarCapturasVencidas(AHORA)).thenReturn(1);
        when(repositorio.buscarActivaDePropietario(DUENO_ID, 4, 9, HUELLA_SESION, AHORA))
                .thenReturn(Optional.empty());
        ServicioRfid1 servicio = servicio(repositorio, transacciones, publicador);

        assertTrue(servicio.consultarCapturaActiva(HUELLA_SESION, DUENO).isEmpty());

        verify(publicador).publicarSiActualizada(true);
        assertEquals(1, transacciones.confirmadas);
    }

    @Test
    void uuidV5ConservaLaSecuenciaHexadecimalYElAnchoTransmitido() {
        assertEquals("f0cfb68e-1b70-5bb5-b0e2-b9c33aec7998", ClavesRfid1.uuidV5(CAPTURA_ID, "000A"));
        assertNotEquals(ClavesRfid1.uuidV5(CAPTURA_ID, "000A"), ClavesRfid1.uuidV5(CAPTURA_ID, "A"));
    }

    @Test
    void conflictoDeUidSeConfirmaAntesDeTraducirseA409() {
        RepositorioRfid1 repositorio = org.mockito.Mockito.mock(RepositorioRfid1.class);
        AdministradorTransaccionesFalso transacciones = new AdministradorTransaccionesFalso();
        PublicadorCapturaRfid1 publicador = org.mockito.Mockito.mock(PublicadorCapturaRfid1.class);
        doAnswer(invocacion -> {
            assertEquals(1, transacciones.confirmadas);
            return null;
        }).when(publicador).publicarSiActualizada(true);
        ServicioRfid1 servicio = servicio(repositorio, transacciones, publicador);
        String claveLectura = ClavesRfid1.uuidV5(CAPTURA_ID, "000A");
        when(repositorio.completarLectura(CAPTURA_ID, "000A", "04A1B2C3", ClavesRfid1.huellaUid("04A1B2C3"), AHORA))
                .thenReturn(new ResultadoLecturaRfid1("ESCANEANDO", null, "TARJETA_YA_REGISTRADA", false));

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> servicio.procesarLectura(CAPTURA_ID, "000a", "04a1b2c3", claveLectura));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertEquals("TARJETA_YA_REGISTRADA", error.codigo());
        assertEquals(1, transacciones.confirmadas);
        assertEquals(0, transacciones.revertidas);
        verify(publicador).publicarSiActualizada(true);
    }

    private static ServicioRfid1 servicio(
            RepositorioRfid1 repositorio, AdministradorTransaccionesFalso transacciones) {
        return servicio(repositorio, transacciones, org.mockito.Mockito.mock(PublicadorCapturaRfid1.class));
    }

    private static ServicioRfid1 servicio(
            RepositorioRfid1 repositorio,
            AdministradorTransaccionesFalso transacciones,
            PublicadorCapturaRfid1 publicador) {
        return servicio(repositorio, transacciones, publicador, TipoEstacionamiento.PUBLICO);
    }

    private static ServicioRfid1 servicio(
            RepositorioRfid1 repositorio,
            AdministradorTransaccionesFalso transacciones,
            TipoEstacionamiento modalidad) {
        return servicio(repositorio, transacciones,
                org.mockito.Mockito.mock(PublicadorCapturaRfid1.class), modalidad);
    }

    private static ServicioRfid1 servicio(
            RepositorioRfid1 repositorio,
            AdministradorTransaccionesFalso transacciones,
            PublicadorCapturaRfid1 publicador,
            TipoEstacionamiento modalidad) {
        return new ServicioRfid1(
                repositorio, configuracion(modalidad), transacciones, Clock.fixed(AHORA, ZoneOffset.UTC), publicador);
    }

    private static RepositorioConfiguracion configuracion(TipoEstacionamiento modalidad) {
        RepositorioConfiguracion repositorio = org.mockito.Mockito.mock(RepositorioConfiguracion.class);
        ConfiguracionPersistida valor = new ConfiguracionPersistida(
                EstadoConfiguracion.CONFIGURADA, 1, 1, null, null, null, null, null, null, null, null,
                modalidad, null, null, null, null, null, null, null, null, null, null, null, null);
        org.mockito.Mockito.when(repositorio.bloquear()).thenReturn(valor);
        return repositorio;
    }

    private static CapturaRfid1Persistida captura(String estado) {
        return new CapturaRfid1Persistida(
                CAPTURA_ID, "CLIENTE", "CLI-0001", CLIENTE_ID, null, DUENO_ID, 4, 9, HUELLA_SESION,
                "hash-clave", "huella-solicitud", null, null, estado, null, null,
                AHORA, AHORA.plusSeconds(120), null, null, null, null, null, null);
    }

    private static final class AdministradorTransaccionesFalso implements PlatformTransactionManager {
        private int confirmadas;
        private int revertidas;

        @Override
        public TransactionStatus getTransaction(TransactionDefinition definicion) {
            return new SimpleTransactionStatus();
        }

        @Override
        public void commit(TransactionStatus estado) {
            confirmadas++;
        }

        @Override
        public void rollback(TransactionStatus estado) {
            revertidas++;
        }
    }
}
