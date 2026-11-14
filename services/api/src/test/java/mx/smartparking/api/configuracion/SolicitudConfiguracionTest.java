package mx.smartparking.api.configuracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

class SolicitudConfiguracionTest {

    @Test
    void normalizaCorreoConTrimAntesDePersistirlo() {
        SolicitudConfiguracion solicitud = conPropietario(
                solicitud("09:00", "17:00", "UTC", "acceso-123", "admin-1234").propietario(),
                "Ana María", "López", "García", "\u2003Operador@Example.Test\u2003");

        assertEquals("\u2003operador@example.test\u2003", solicitud.validar().propietario().correo());
    }

    @Test
    void aceptaIntervaloDiarioQueCruzaMedianoche() {
        DatosConfiguracion datos = solicitud(
                "22:00",
                "06:00",
                "America/Mexico_City",
                "Acceso seguro 2026",
                "Administracion 2026").validar();

        assertEquals(ModoHorario.INTERVALO_DIARIO, datos.horario().modo());
        assertEquals("America/Mexico_City", datos.horario().zonaHoraria());
        assertEquals("operador@example.test", datos.propietario().correo());
        assertNotNull(datos.horario().horaCierre());
    }

    @Test
    void rechazaHorasIgualesFormatoNoCanonicoYZonaFija() {
        assertThrows(IllegalArgumentException.class,
                () -> solicitud("09:00", "09:00", "America/Mexico_City", "Acceso seguro 2026", "Admin seguro 2026").validar());
        assertThrows(IllegalArgumentException.class,
                () -> solicitud("24:00", "06:00", "America/Mexico_City", "Acceso seguro 2026", "Admin seguro 2026").validar());
        assertThrows(IllegalArgumentException.class,
                () -> solicitud("09:00", "17:00", "+01:00", "Acceso seguro 2026", "Admin seguro 2026").validar());
    }

    @Test
    void rechazaContrasenasCortasOIguales() {
        assertThrows(IllegalArgumentException.class,
                () -> solicitud("09:00", "17:00", "UTC", "corta", "Admin seguro 2026").validar());
        assertThrows(IllegalArgumentException.class,
                () -> solicitud("09:00", "17:00", "UTC", "misma-contraseña-2026", "misma-contraseña-2026").validar());
    }

    @Test
    void aceptaDiezCaracteresYRechazaNueveEnCadaContrasena() {
        SolicitudConfiguracion valida = solicitud(
                "09:00", "17:00", "UTC", "acceso-123", "admin-1234");

        assertEquals("acceso-123", valida.validar().propietario().contrasenaAcceso());
        assertEquals("admin-1234", valida.validar().propietario().contrasenaAdministrativa());
        assertThrows(IllegalArgumentException.class,
                () -> solicitud("09:00", "17:00", "UTC", "acceso-12", "admin-1234").validar());
        assertThrows(IllegalArgumentException.class,
                () -> solicitud("09:00", "17:00", "UTC", "acceso-123", "admin-123").validar());
    }

    @Test
    void mideElMinimoDeContrasenaEnPuntosDeCodigoUnicode() {
        String nuevePuntosAcceso = "a".repeat(8) + "🚗";
        String nuevePuntosAdmin = "b".repeat(8) + "🔐";
        String diezPuntosAcceso = "c".repeat(9) + "🚗";
        String diezPuntosAdmin = "d".repeat(9) + "🔐";

        SolicitudConfiguracion accesoCorto = crearSolicitud(
                "Ana", "López", null, "ana@example.test", nuevePuntosAcceso, diezPuntosAdmin,
                "Centro", TipoEstacionamiento.PUBLICO, "UTC", "09:00", "17:00");
        SolicitudConfiguracion adminCorto = crearSolicitud(
                "Ana", "López", null, "ana@example.test", diezPuntosAcceso, nuevePuntosAdmin,
                "Centro", TipoEstacionamiento.PUBLICO, "UTC", "09:00", "17:00");
        SolicitudConfiguracion ambasValidas = crearSolicitud(
                "Ana", "López", null, "ana@example.test", diezPuntosAcceso, diezPuntosAdmin,
                "Centro", TipoEstacionamiento.PUBLICO, "UTC", "09:00", "17:00");

        assertThrows(IllegalArgumentException.class, accesoCorto::validar);
        assertThrows(IllegalArgumentException.class, adminCorto::validar);
        assertEquals(diezPuntosAcceso, ambasValidas.validar().propietario().contrasenaAcceso());
        assertEquals(diezPuntosAdmin, ambasValidas.validar().propietario().contrasenaAdministrativa());
    }

    @Test
    void validaCamposObligatoriosYPermiteSegundoApellidoVacio() {
        SolicitudConfiguracion base = solicitud("09:00", "17:00", "UTC", "acceso-123", "admin-1234");
        SolicitudConfiguracion.PropietarioSolicitud propietario = base.propietario();

        assertNull(conPropietario(propietario, propietario.nombres(), propietario.primerApellido(), " ",
                propietario.correo()).validar().propietario().segundoApellido());
        assertThrows(IllegalArgumentException.class,
                () -> conPropietario(propietario, " ", propietario.primerApellido(), null, propietario.correo()).validar());
        assertThrows(IllegalArgumentException.class,
                () -> conPropietario(propietario, propietario.nombres(), "", null, propietario.correo()).validar());
        assertThrows(IllegalArgumentException.class,
                () -> conPropietario(propietario, propietario.nombres(), propietario.primerApellido(), null, "correo-invalido").validar());
        assertThrows(IllegalArgumentException.class,
                () -> new SolicitudConfiguracion(null, base.estacionamiento()).validar());
        assertThrows(IllegalArgumentException.class,
                () -> new SolicitudConfiguracion(propietario, null).validar());
        assertThrows(IllegalArgumentException.class,
                () -> new SolicitudConfiguracion(propietario,
                        new SolicitudConfiguracion.EstacionamientoSolicitud("Centro", TipoEstacionamiento.PUBLICO, null)).validar());
    }

    @Test
    void respetaLimitesDeCamposDeTexto() {
        SolicitudConfiguracion maxima = crearSolicitud(
                "N".repeat(120),
                "P".repeat(80),
                "M".repeat(80),
                "c".repeat(250) + "@x.c",
                "acceso-123",
                "admin-1234",
                "E".repeat(120),
                TipoEstacionamiento.MIXTO,
                "UTC",
                "09:00",
                "17:00");

        assertNotNull(maxima.validar());
        assertThrows(IllegalArgumentException.class,
                () -> crearSolicitud("N".repeat(121), "López", null, "ana@example.test",
                        "acceso-123", "admin-1234", "Centro", TipoEstacionamiento.PUBLICO,
                        "UTC", "09:00", "17:00").validar());
        assertThrows(IllegalArgumentException.class,
                () -> crearSolicitud("Ana", "P".repeat(81), null, "ana@example.test",
                        "acceso-123", "admin-1234", "Centro", TipoEstacionamiento.PUBLICO,
                        "UTC", "09:00", "17:00").validar());
        assertThrows(IllegalArgumentException.class,
                () -> crearSolicitud("Ana", "López", "M".repeat(81), "ana@example.test",
                        "acceso-123", "admin-1234", "Centro", TipoEstacionamiento.PUBLICO,
                        "UTC", "09:00", "17:00").validar());
        assertThrows(IllegalArgumentException.class,
                () -> crearSolicitud("Ana", "López", null, "ana@example.test",
                        "acceso-123", "admin-1234", "E".repeat(121), TipoEstacionamiento.PUBLICO,
                        "UTC", "09:00", "17:00").validar());
        assertThrows(IllegalArgumentException.class,
                () -> crearSolicitud("Ana", "López", null, "c".repeat(251) + "@x.c",
                        "acceso-123", "admin-1234", "Centro", TipoEstacionamiento.PUBLICO,
                        "UTC", "09:00", "17:00").validar());
        assertThrows(IllegalArgumentException.class,
                () -> crearSolicitud("Ana", "López", null, "ana@example.test",
                        "acceso-123", "admin-1234", " ", TipoEstacionamiento.PUBLICO,
                        "UTC", "09:00", "17:00").validar());
        assertThrows(IllegalArgumentException.class,
                () -> crearSolicitud("Ana", "López", null, "ana@example.test",
                        "acceso-123", "admin-1234", "Centro", null,
                        "UTC", "09:00", "17:00").validar());
    }

    @Test
    void rechazaZonaHorariaAusenteODesconocidaYHorasNoCanonicas() {
        assertThrows(IllegalArgumentException.class,
                () -> solicitud("09:00", "17:00", null, "acceso-123", "admin-1234").validar());
        assertThrows(IllegalArgumentException.class,
                () -> solicitud("09:00", "17:00", "America/Zona_Inexistente", "acceso-123", "admin-1234").validar());
        assertThrows(IllegalArgumentException.class,
                () -> solicitud("9:00", "17:00", "UTC", "acceso-123", "admin-1234").validar());
        assertThrows(IllegalArgumentException.class,
                () -> solicitud("09:00:00", "17:00", "UTC", "acceso-123", "admin-1234").validar());
    }

    @Test
    void aceptaHorarioContinuoSinHoras() {
        SolicitudConfiguracion solicitud = solicitud("", "", "UTC", "Acceso seguro 2026", "Admin seguro 2026");
        solicitud = new SolicitudConfiguracion(
                solicitud.propietario(),
                new SolicitudConfiguracion.EstacionamientoSolicitud(
                        solicitud.estacionamiento().nombre(),
                        solicitud.estacionamiento().tipo(),
                        new SolicitudConfiguracion.HorarioSolicitud(
                                ModoHorario.CONTINUO_24_7, "UTC", null, null)));

        assertEquals(ModoHorario.CONTINUO_24_7, solicitud.validar().horario().modo());
    }

    private static SolicitudConfiguracion solicitud(
            String apertura,
            String cierre,
            String zona,
            String contrasenaAcceso,
            String contrasenaAdministrativa) {
        return crearSolicitud(
                "Ana María", "López", "García", " Operador@Example.Test ",
                contrasenaAcceso, contrasenaAdministrativa, "Centro", TipoEstacionamiento.PUBLICO,
                zona, apertura, cierre);
    }

    private static SolicitudConfiguracion conPropietario(
            SolicitudConfiguracion.PropietarioSolicitud anterior,
            String nombres,
            String primerApellido,
            String segundoApellido,
            String correo) {
        return new SolicitudConfiguracion(
                new SolicitudConfiguracion.PropietarioSolicitud(
                        nombres,
                        primerApellido,
                        segundoApellido,
                        correo,
                        anterior.contrasenaAcceso(),
                        anterior.contrasenaAdministrativa()),
                new SolicitudConfiguracion.EstacionamientoSolicitud(
                        "Centro",
                        TipoEstacionamiento.PUBLICO,
                        new SolicitudConfiguracion.HorarioSolicitud(
                                ModoHorario.INTERVALO_DIARIO, "UTC", "09:00", "17:00")));
    }

    private static SolicitudConfiguracion crearSolicitud(
            String nombres,
            String primerApellido,
            String segundoApellido,
            String correo,
            String contrasenaAcceso,
            String contrasenaAdministrativa,
            String nombreEstacionamiento,
            TipoEstacionamiento tipo,
            String zona,
            String apertura,
            String cierre) {
        return new SolicitudConfiguracion(
                new SolicitudConfiguracion.PropietarioSolicitud(
                        nombres,
                        primerApellido,
                        segundoApellido,
                        correo,
                        contrasenaAcceso,
                        contrasenaAdministrativa),
                new SolicitudConfiguracion.EstacionamientoSolicitud(
                        nombreEstacionamiento,
                        tipo,
                        new SolicitudConfiguracion.HorarioSolicitud(
                                ModoHorario.INTERVALO_DIARIO, zona, apertura, cierre)));
    }
}
