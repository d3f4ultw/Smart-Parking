package mx.smartparking.ownerconsole.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Map;
import mx.smartparking.ownerconsole.modelo.BorradorConfiguracion;
import mx.smartparking.ownerconsole.modelo.PasoConfiguracion;
import org.junit.jupiter.api.Test;

class ValidadorConfiguracionTest {

    private final ValidadorConfiguracion validador = new ValidadorConfiguracion();

    @Test
    void elAsistenteTieneExactamenteSeisVistas() {
        assertEquals(6, PasoConfiguracion.values().length);
    }

    @Test
    void aceptaUnHorarioQueCruzaLaMedianoche() {
        BorradorConfiguracion borrador = crearHorario("22:30", "06:15", "America/Mexico_City");

        assertTrue(validador.validar(PasoConfiguracion.HORARIO, borrador).isEmpty());
    }

    @Test
    void rechazaHorasIgualesYFormatoDe24Horas() {
        BorradorConfiguracion horasIguales = crearHorario("09:00", "09:00", "America/Mexico_City");
        BorradorConfiguracion finDelDia = crearHorario("09:00", "24:00", "America/Mexico_City");

        assertTrue(validador.validar(PasoConfiguracion.HORARIO, horasIguales).containsKey("horaCierre"));
        assertTrue(validador.validar(PasoConfiguracion.HORARIO, finDelDia).containsKey("horaCierre"));
    }

    @Test
    void requiereUnaZonaIanaExplicitaAunEnModoContinuo() {
        BorradorConfiguracion borrador = crearHorario("", "", "");
        borrador.actualizarHorario("CONTINUO_24_7", "", "", "");

        Map<String, String> errores = validador.validar(PasoConfiguracion.HORARIO, borrador);

        assertEquals("Selecciona una zona horaria.", errores.get("zonaHoraria"));
        assertFalse(errores.containsKey("horaApertura"));
    }

    @Test
    void rechazaContrasenaDeAccesoDeNueveCaracteres() {
        BorradorConfiguracion borrador = new BorradorConfiguracion();
        borrador.actualizarAcceso("dueno@example.com", "123456789".toCharArray());

        Map<String, String> errores = validador.validar(PasoConfiguracion.ACCESO, borrador);

        assertTrue(errores.containsKey("contrasenaAcceso"));
    }

    @Test
    void aceptaContrasenaDeAccesoDeDiezCaracteres() {
        BorradorConfiguracion borrador = new BorradorConfiguracion();
        borrador.actualizarAcceso("dueno@example.com", "1234567890".toCharArray());

        Map<String, String> errores = validador.validar(PasoConfiguracion.ACCESO, borrador);

        assertFalse(errores.containsKey("contrasenaAcceso"));
    }

    @Test
    void rechazaContrasenaAdministrativaDeNueveCaracteres() {
        BorradorConfiguracion borrador = borradorConAccesoYAdministracion("123456789");

        Map<String, String> errores = validador.validar(PasoConfiguracion.ADMINISTRACION, borrador);

        assertTrue(errores.containsKey("contrasenaAdministrativa"));
    }

    @Test
    void aceptaContrasenaAdministrativaDeDiezCaracteres() {
        BorradorConfiguracion borrador = borradorConAccesoYAdministracion("1234567890");

        Map<String, String> errores = validador.validar(PasoConfiguracion.ADMINISTRACION, borrador);

        assertFalse(errores.containsKey("contrasenaAdministrativa"));
        assertFalse(errores.containsKey("confirmacionAdministrativa"));
    }

    @Test
    void rechazaUnaConfirmacionAdministrativaDistinta() {
        BorradorConfiguracion borrador = new BorradorConfiguracion();
        borrador.actualizarAcceso("dueno@example.com", "Acceso-123456".toCharArray(), "Acceso-123456".toCharArray());
        borrador.actualizarAdministracion("Acceso-123456".toCharArray(), "Otra-12345678".toCharArray());

        Map<String, String> errores = validador.validar(PasoConfiguracion.ADMINISTRACION, borrador);

        assertTrue(errores.containsKey("confirmacionAdministrativa"));
    }

    @Test
    void rechazaUsarLaMismaContrasenaParaAccesoYAdministracion() {
        BorradorConfiguracion borrador = new BorradorConfiguracion();
        borrador.actualizarAcceso("dueno@example.com", "Acceso-123456".toCharArray(), "Acceso-123456".toCharArray());
        borrador.actualizarAdministracion("Acceso-123456".toCharArray(), "Acceso-123456".toCharArray());

        Map<String, String> errores = validador.validar(PasoConfiguracion.ADMINISTRACION, borrador);

        assertTrue(errores.containsKey("contrasenaAdministrativa"));
    }

    @Test
    void payloadNoIncluyeConfirmaciones() throws Exception {
        BorradorConfiguracion borrador = new BorradorConfiguracion();
        borrador.actualizarIdentidad("Ana", "López", "Ríos");
        borrador.actualizarAcceso(
                "ana@example.com", "Acceso-123456".toCharArray(), "confirmacion-acceso-no-enviar".toCharArray());
        borrador.actualizarAdministracion(
                "Admin-987654321".toCharArray(), "confirmacion-admin-no-enviar".toCharArray());
        borrador.actualizarEstacionamiento("Centro", "PUBLICO");
        borrador.actualizarHorario("CONTINUO_24_7", "America/Mexico_City", "", "");

        JsonNode payload = new ObjectMapper().readTree(
                new MapeadorSolicitudConfiguracion().mapear(borrador).json());

        assertEquals("ana@example.com", payload.path("propietario").path("correo").asText());
        assertEquals("López", payload.path("propietario").path("primerApellido").asText());
        assertFalse(payload.path("propietario").has("apellidoPaterno"));
        assertFalse(payload.path("propietario").has("apellidoMaterno"));
        assertFalse(payload.toString().contains("confirmacion-acceso-no-enviar"));
        assertFalse(payload.toString().contains("confirmacion-admin-no-enviar"));
        assertEquals("America/Mexico_City", payload.path("estacionamiento").path("horario").path("zonaHoraria").asText());
        assertTrue(payload.path("estacionamiento").path("horario").path("horaApertura").isNull());
        assertTrue(payload.path("estacionamiento").path("horario").path("horaCierre").isNull());
    }

    @Test
    void elPayloadAceptaSegundoApellidoAusente() throws Exception {
        BorradorConfiguracion borrador = new BorradorConfiguracion();
        borrador.actualizarIdentidad("Ana", "López", null);
        borrador.actualizarAcceso("ana@example.com", "Acceso-123456".toCharArray());
        borrador.actualizarAdministracion(
                "Admin-987654321".toCharArray(), "Admin-987654321".toCharArray());
        borrador.actualizarEstacionamiento("Centro", "PUBLICO");
        borrador.actualizarHorario("CONTINUO_24_7", "America/Mexico_City", "", "");

        JsonNode payload = new ObjectMapper().readTree(
                new MapeadorSolicitudConfiguracion().mapear(borrador).json());

        assertEquals("López", payload.path("propietario").path("primerApellido").asText());
        assertTrue(payload.path("propietario").path("segundoApellido").isNull());
        assertTrue(payload.path("estacionamiento").path("horario").path("horaApertura").isNull());
        assertTrue(payload.path("estacionamiento").path("horario").path("horaCierre").isNull());
    }

    @Test
    void limpiarSecretosEliminaLasCuatroCredencialesDelBorrador() {
        BorradorConfiguracion borrador = new BorradorConfiguracion();
        borrador.actualizarAcceso("dueno@example.com", "Acceso-123456".toCharArray(), "Acceso-123456".toCharArray());
        borrador.actualizarAdministracion("Admin-987654321".toCharArray(), "Admin-987654321".toCharArray());

        borrador.limpiarSecretos();

        assertEquals(0, borrador.copiarContrasenaAcceso().length);
        assertEquals(0, borrador.copiarConfirmacionAcceso().length);
        assertEquals(0, borrador.copiarContrasenaAdministrativa().length);
        assertEquals(0, borrador.copiarConfirmacionAdministrativa().length);
    }

    private BorradorConfiguracion crearHorario(String apertura, String cierre, String zona) {
        BorradorConfiguracion borrador = new BorradorConfiguracion();
        borrador.actualizarHorario("INTERVALO_DIARIO", zona, apertura, cierre);
        return borrador;
    }

    private BorradorConfiguracion borradorConAccesoYAdministracion(String administrativa) {
        BorradorConfiguracion borrador = new BorradorConfiguracion();
        borrador.actualizarAcceso("dueno@example.com", "ContrasenaAcceso!".toCharArray());
        char[] secreto = administrativa.toCharArray();
        borrador.actualizarAdministracion(secreto, administrativa.toCharArray());
        return borrador;
    }
}
