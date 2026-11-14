package mx.smartparking.api.integracion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;
import static mx.smartparking.api.integracion.PropietarioApiAceptacionSupport.*;

import java.net.URI;
import java.net.http.HttpResponse;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;
import mx.smartparking.api.integracion.ApiCliente;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;

/**
 * Aceptación HTTP opt-in contra una API local conectada únicamente a PostgreSQL descartable.
 *
 * <p>Por omisión no realiza conexiones. Para ejecutarla se requieren tanto
 * {@code -Dsmartparking.integration.disposable=true} como
 * {@code -Dsmartparking.api-url=http://127.0.0.1:8180}. El host debe resolver
 * exclusivamente a direcciones loopback. El entorno indicado debe usar su propio
 * PostgreSQL 18.6 aislado y no el volumen persistente del proyecto.</p>
 */
class PropietarioApiAceptacionTest {

    private static final String CSRF = "X-CSRF-TOKEN";
    private static final String ESTADO = "/api/v1/configuracion/estado";
    private static final String SESION = "/api/v1/sesion";

    @Test
    void completaElCicloDePropietarioConSeguridadYTransferencia() throws Exception {
        URI base = baseUrlOptIn();
        URI mailpit = MailpitApiCliente.baseUrlOptIn("smartparking.mailpit-url");
        assertEquals(0, MailpitApiCliente.cantidadMensajes(mailpit),
                "El Mailpit del proyecto de aceptación debe iniciar vacío.");
        ApiCliente api = new ApiCliente(base);
        String sufijo = UUID.randomUUID().toString().replace("-", "");
        String correoAnterior = "fase3." + sufijo + "@example.test";
        String claveAccesoAnterior = "\u2003" + "á".repeat(129) + " 🚗 " + "\u2003";
        String claveAdministrativaAnterior = "administracion inicial robusta 2026 B!";
        String claveAccesoNueva = "acceso nuevo robusto 2026 C!";
        String claveAdministrativaNueva = "administracion nueva robusta 2026 D!";

        HttpResponse<String> estadoInicial = api.get(ESTADO);
        assertEquals(200, estadoInicial.statusCode(), "La API aislada debe responder al estado público.");
        JsonNode cuerpoEstado = leerJson(estadoInicial.body());
        assertEquals(1, cuerpoEstado.size(), "El estado público no debe revelar otros datos.");
        assertEquals("SIN_CONFIGURAR", texto(cuerpoEstado, "estado"),
                "La aceptación solo escribe en una base descartable recién creada.");

        String csrfInicial = api.obtenerCsrf(true);
        String cookieAntesLogin = api.cookie("JSESSIONID");
        assertNotNull(cookieAntesLogin, "La API debe mantener la sesión con una cookie.");

        Map<String, Object> configuracionAnterior = configuracion(
                correoAnterior,
                claveAccesoAnterior,
                claveAdministrativaAnterior,
                "Estacionamiento de prueba");
        HttpResponse<String> sinCsrf = api.post(
                "/api/v1/configuracion/inicial",
                configuracionAnterior,
                clave("setup-sin-csrf-" + sufijo),
                null);
        assertEquals(403, sinCsrf.statusCode(), "Las escrituras deben exigir CSRF.");
        assertEstado(api, "SIN_CONFIGURAR");

        String claveInicial = clave("setup-inicial-" + sufijo);
        HttpResponse<String> configurada = api.post(
                "/api/v1/configuracion/inicial", configuracionAnterior, claveInicial, csrfInicial);
        assertEquals(201, configurada.statusCode(), "La configuración inicial debe confirmarse una vez.");
        JsonNode resultadoInicial = leerJson(configurada.body());
        assertEquals("CONFIGURADA", texto(resultadoInicial, "estado"));
        long revisionInicial = numero(resultadoInicial, "revision");
        assertAviso(resultadoInicial, "avisoBienvenida");
        verificarSinSecretos(configurada.body(), claveAccesoAnterior, claveAdministrativaAnterior);

        HttpResponse<String> duplicada = api.post(
                "/api/v1/configuracion/inicial", configuracionAnterior, claveInicial, csrfInicial);
        assertEquals(201, duplicada.statusCode(), "El retry idempotente debe devolver la operación original.");
        JsonNode resultadoDuplicado = leerJson(duplicada.body());
        assertEquals(revisionInicial, numero(resultadoDuplicado, "revision"));
        assertEquals(texto(resultadoInicial, "avisoBienvenida"), texto(resultadoDuplicado, "avisoBienvenida"));
        assertEquals(1, MailpitApiCliente.cantidadMensajes(mailpit),
                "El retry idempotente no debe enviar otra bienvenida.");
        assertEquals(1, MailpitApiCliente.cantidadPorAsunto(
                mailpit, "Configuración de Smart Parking completada"));
        String bienvenidaInicial = MailpitApiCliente.textoUnico(
                mailpit, "Configuración de Smart Parking completada", correoAnterior);
        assertTrue(bienvenidaInicial.contains("Estacionamiento de prueba"),
                "La bienvenida debe incluir el nombre configurado.");
        verificarCorreoSinSecretos(
                bienvenidaInicial, claveAccesoAnterior, claveAdministrativaAnterior);

        HttpResponse<String> loginAdministrativo = api.postJson(
                SESION,
                Map.of("correo", correoAnterior, "contrasena", claveAdministrativaAnterior),
                Map.of(CSRF, csrfInicial));
        assertEquals(401, loginAdministrativo.statusCode(),
                "La contraseña administrativa no debe autenticar al propietario.");
        verificarSinSecretos(loginAdministrativo.body(), claveAdministrativaAnterior);

        HttpResponse<String> loginSinCsrf = api.postJson(
                SESION,
                Map.of("correo", correoAnterior, "contrasena", claveAccesoAnterior),
                Map.of());
        assertEquals(403, loginSinCsrf.statusCode(), "El login también debe exigir CSRF.");

        HttpResponse<String> login = api.postJson(
                SESION,
                Map.of("correo", correoAnterior, "contrasena", claveAccesoAnterior),
                Map.of(CSRF, csrfInicial));
        assertEquals(200, login.statusCode(), "La contraseña de acceso debe autenticar al propietario.");
        JsonNode resultadoLogin = leerJson(login.body());
        assertTrue(resultadoLogin.path("autenticada").asBoolean(), "El propietario debe quedar autenticado.");
        assertEquals(correoAnterior, texto(resultadoLogin, "correo"));
        String csrfAutenticado = texto(resultadoLogin, "csrfToken");
        assertFalse(csrfAutenticado.isBlank(), "El login debe renovar CSRF.");
        assertTrue(!csrfInicial.equals(csrfAutenticado), "El login debe rotar el token CSRF.");
        String cookieDespuesLogin = api.cookie("JSESSIONID");
        assertTrue(cookieAntesLogin != null && cookieDespuesLogin != null
                        && !cookieAntesLogin.equals(cookieDespuesLogin),
                "El login debe rotar el ID de sesión.");
        api.csrf(csrfAutenticado);

        HttpResponse<String> panelInicial = api.get("/api/v1/panel");
        assertEquals(200, panelInicial.statusCode(), "La sesión activa debe consultar el panel.");
        verificarSinSecretos(panelInicial.body(), claveAccesoAnterior, claveAdministrativaAnterior);
        JsonNode datosPanelInicial = leerJson(panelInicial.body());
        String etagInicial = etag(panelInicial);
        String nombreOriginal = texto(datosPanelInicial.path("estacionamiento"), "nombre");
        assertEquals("Estacionamiento de prueba", nombreOriginal);

        HttpResponse<String> patchNombreSinCsrf = api.patchSinCsrf(
                "/api/v1/estacionamiento",
                Map.of("nombre", "Nombre sin CSRF"),
                etagInicial,
                clave("rename-sin-csrf-" + sufijo));
        assertEquals(403, patchNombreSinCsrf.statusCode(), "El PATCH de nombre debe exigir CSRF.");
        assertEquals(etagInicial, etag(api.get("/api/v1/panel")),
                "El PATCH rechazado no debe avanzar la revisión.");

        HttpResponse<String> renombrado = api.patch(
                "/api/v1/estacionamiento",
                Map.of("nombre", "Estacionamiento renombrado"),
                etagInicial,
                clave("rename-" + sufijo));
        assertEquals(200, renombrado.statusCode(), "El propietario debe poder cambiar solo el nombre.");
        String etagTrasRenombrar = etag(renombrado);
        assertTrue(!etagInicial.equals(etagTrasRenombrar), "El rename debe avanzar la revisión.");
        assertEquals("Estacionamiento renombrado",
                texto(leerJson(renombrado.body()).path("estacionamiento"), "nombre"));

        HttpResponse<String> revisionObsoleta = api.patch(
                "/api/v1/estacionamiento",
                Map.of("nombre", "Nombre obsoleto"),
                etagInicial,
                clave("rename-stale-" + sufijo));
        assertEquals(412, revisionObsoleta.statusCode(), "If-Match obsoleto debe rechazarse.");

        List<HttpResponse<String>> respuestasConcurrentes = api.patchConcurrentes(
                etagTrasRenombrar,
                clave("rename-concurrente-a-" + sufijo),
                clave("rename-concurrente-b-" + sufijo));
        Set<Integer> codigosConcurrentes = respuestasConcurrentes.stream()
                .map(HttpResponse::statusCode)
                .collect(Collectors.toCollection(HashSet::new));
        assertEquals(Set.of(200, 412), codigosConcurrentes,
                "Solo una escritura concurrente con la misma revisión debe ganar.");

        HttpResponse<String> panelActual = api.get("/api/v1/panel");
        assertEquals(200, panelActual.statusCode());
        String etagActual = etag(panelActual);
        String nombreAntesTransferencia = texto(leerJson(panelActual.body()).path("estacionamiento"), "nombre");

        Map<String, Object> datosEstacionamiento = Map.of(
                "tipo", "MIXTO",
                "horario", Map.of(
                        "modo", "CONTINUO_24_7",
                        "zonaHoraria", "America/Mexico_City",
                        "horaApertura", "",
                        "horaCierre", ""));
        HttpResponse<String> patchDatosSinCsrf = api.patchSinCsrf(
                "/api/v1/estacionamiento/datos",
                datosEstacionamiento,
                etagActual,
                clave("datos-sin-csrf-" + sufijo));
        assertEquals(403, patchDatosSinCsrf.statusCode(), "El PATCH de tipo y horario debe exigir CSRF.");
        assertEquals(etagActual, etag(api.get("/api/v1/panel")),
                "El PATCH de tipo y horario rechazado no debe avanzar la revisión.");

        String claveDatos = clave("datos-estacionamiento-" + sufijo);
        HttpResponse<String> datosActualizados = api.patch(
                "/api/v1/estacionamiento/datos", datosEstacionamiento, etagActual, claveDatos);
        assertEquals(200, datosActualizados.statusCode(), "El propietario debe poder cambiar tipo y horario.");
        JsonNode panelConDatos = leerJson(datosActualizados.body());
        long revisionDatos = numero(panelConDatos, "revision");
        assertTrue(!etagActual.equals(etag(datosActualizados)), "La edición debe avanzar ETag.");
        assertEquals("MIXTO", texto(panelConDatos.path("estacionamiento"), "tipo"));
        JsonNode horarioActualizado = panelConDatos.path("estacionamiento").path("horario");
        assertEquals("CONTINUO_24_7", texto(horarioActualizado, "modo"));
        assertTrue(horarioActualizado.path("horaApertura").isNull(),
                "El horario 24/7 no debe persistir hora de apertura.");
        assertTrue(horarioActualizado.path("horaCierre").isNull(),
                "El horario 24/7 no debe persistir hora de cierre.");

        HttpResponse<String> repeticionDatos = api.patch(
                "/api/v1/estacionamiento/datos", datosEstacionamiento, etagActual, claveDatos);
        assertEquals(200, repeticionDatos.statusCode(), "El retry idempotente de datos debe devolver éxito.");
        assertEquals(revisionDatos, numero(leerJson(repeticionDatos.body()), "revision"));
        assertEquals(revisionDatos, numero(leerJson(api.get("/api/v1/panel").body()), "revision"),
                "La lectura posterior debe confirmar la persistencia sin otra revisión.");
        assertEquals(1, revisionDatos - numero(leerJson(panelActual.body()), "revision"),
                "La edición de tipo y horario debe crear una sola revisión.");

        panelActual = api.get("/api/v1/panel");
        assertEquals(200, panelActual.statusCode());
        etagActual = etag(panelActual);

        HttpResponse<String> iniciarSinCsrf = api.post(
                "/api/v1/transferencia/iniciar",
                Map.of("contrasenaAdministrativa", claveAdministrativaAnterior),
                clave("transfer-sin-csrf-" + sufijo),
                null);
        assertEquals(403, iniciarSinCsrf.statusCode(), "El inicio de transferencia debe exigir CSRF.");
        assertEstado(api, "CONFIGURADA");
        HttpResponse<String> adminIncorrecto = api.postConCsrf(
                "/api/v1/transferencia/iniciar",
                Map.of("contrasenaAdministrativa", "clave administrativa incorrecta 2026"),
                Map.of("If-Match", etagActual, "Idempotency-Key", clave("transfer-bad-" + sufijo)));
        assertEquals(403, adminIncorrecto.statusCode(), "Una contraseña administrativa incorrecta debe denegarse.");
        assertEstado(api, "CONFIGURADA");
        assertEquals(nombreAntesTransferencia,
                texto(leerJson(api.get("/api/v1/panel").body()).path("estacionamiento"), "nombre"));

        HttpResponse<String> inicio = api.postConCsrf(
                "/api/v1/transferencia/iniciar",
                Map.of("contrasenaAdministrativa", claveAdministrativaAnterior),
                Map.of("If-Match", etagActual, "Idempotency-Key", clave("transfer-start-" + sufijo)));
        assertEquals(200, inicio.statusCode(), "La clave administrativa correcta debe desvincular de inmediato.");
        JsonNode resultadoInicio = leerJson(inicio.body());
        assertEquals("TRANSFERENCIA_PENDIENTE", texto(resultadoInicio, "estado"));
        String grantOriginal = texto(resultadoInicio, "grant");
        assertFalse(grantOriginal.isBlank(), "La transferencia debe devolver el grant solo al iniciador.");
        assertAviso(resultadoInicio, "avisoTransferencia");
        verificarSinSecretos(inicio.body(), claveAdministrativaAnterior);
        assertEstado(api, "TRANSFERENCIA_PENDIENTE");
        assertEquals(2, MailpitApiCliente.cantidadMensajes(mailpit),
                "El inicio de transferencia debe enviar un solo aviso.");
        assertEquals(1, MailpitApiCliente.cantidadPorAsunto(mailpit, "Aviso de acceso a Smart Parking"));
        String avisoTransferencia = MailpitApiCliente.textoUnico(
                mailpit, "Aviso de acceso a Smart Parking", correoAnterior);
        assertTrue(avisoTransferencia.contains("se desvinculó"),
                "El aviso debe explicar que el acceso anterior se desvinculó.");
        verificarCorreoSinSecretos(
                avisoTransferencia, claveAccesoAnterior, claveAdministrativaAnterior, grantOriginal);

        HttpResponse<String> sesionRevocada = api.get("/api/v1/panel");
        assertEquals(401, sesionRevocada.statusCode(), "El unlink debe invalidar la sesión previa.");

        String csrfAnonimo = api.obtenerCsrf(false);
        HttpResponse<String> claimPublico = api.post(
                "/api/v1/configuracion/inicial",
                configuracionAnterior,
                clave("public-claim-" + sufijo),
                csrfAnonimo);
        assertEquals(409, claimPublico.statusCode(), "No se permite claim público durante la transferencia.");
        assertEstado(api, "TRANSFERENCIA_PENDIENTE");

        HttpResponse<String> recuperacionIncorrecta = api.postJson(
                "/api/v1/transferencia/recuperar",
                Map.of("contrasenaAdministrativa", "clave administrativa incorrecta 2026"),
                Map.of(CSRF, csrfAnonimo));
        assertEquals(403, recuperacionIncorrecta.statusCode(), "La recuperación exige la clave anterior.");

        HttpResponse<String> recuperacionSinCsrf = api.postJson(
                "/api/v1/transferencia/recuperar",
                Map.of("contrasenaAdministrativa", claveAdministrativaAnterior),
                Map.of());
        assertEquals(403, recuperacionSinCsrf.statusCode(), "La recuperación también debe exigir CSRF.");
        assertEquals(2, MailpitApiCliente.cantidadMensajes(mailpit),
                "La recuperación no debe enviar ni repetir el aviso de transferencia.");

        HttpResponse<String> recuperacion = api.postJson(
                "/api/v1/transferencia/recuperar",
                Map.of("contrasenaAdministrativa", claveAdministrativaAnterior),
                Map.of(CSRF, csrfAnonimo));
        assertEquals(200, recuperacion.statusCode(), "La clave administrativa debe reemitir el grant.");
        JsonNode resultadoRecuperacion = leerJson(recuperacion.body());
        assertEquals("TRANSFERENCIA_PENDIENTE", texto(resultadoRecuperacion, "estado"));
        String grantRecuperado = texto(resultadoRecuperacion, "grant");
        assertFalse(grantRecuperado.isBlank(), "La recuperación debe entregar un grant vigente.");
        assertTrue(!grantOriginal.equals(grantRecuperado), "La recuperación debe rotar el grant.");
        assertTrue(resultadoRecuperacion.get("avisoTransferencia") == null
                        || resultadoRecuperacion.get("avisoTransferencia").isNull(),
                "La recuperación no debe enviar un aviso de transferencia.");

        Map<String, Object> configuracionNueva = configuracion(
                correoAnterior,
                claveAccesoNueva,
                claveAdministrativaNueva,
                "Estacionamiento del nuevo propietario");
        HttpResponse<String> completarSinCsrf = api.postCompletarSinCsrf(
                configuracionNueva, clave("complete-sin-csrf-" + sufijo), grantRecuperado);
        assertEquals(403, completarSinCsrf.statusCode(), "Completar transferencia debe exigir CSRF.");
        assertEstado(api, "TRANSFERENCIA_PENDIENTE");
        HttpResponse<String> grantAntiguo = api.postCompletar(
                configuracionNueva, clave("complete-old-grant-" + sufijo), grantOriginal);
        assertEquals(403, grantAntiguo.statusCode(), "Un grant rotado debe dejar de ser válido.");
        assertEstado(api, "TRANSFERENCIA_PENDIENTE");

        String claveFinalizacion = clave("complete-new-owner-" + sufijo);
        HttpResponse<String> completada = api.postCompletar(
                configuracionNueva, claveFinalizacion, grantRecuperado);
        assertEquals(200, completada.statusCode(), "El grant vigente debe completar la transferencia.");
        JsonNode resultadoCompleto = leerJson(completada.body());
        assertEquals("CONFIGURADA", texto(resultadoCompleto, "estado"));
        assertAviso(resultadoCompleto, "avisoBienvenida");
        verificarSinSecretos(
                completada.body(), claveAccesoNueva, claveAdministrativaNueva, grantRecuperado);
        assertEstado(api, "CONFIGURADA");
        assertEquals(3, MailpitApiCliente.cantidadMensajes(mailpit),
                "La finalización debe enviar una bienvenida nueva y única.");
        assertEquals(2, MailpitApiCliente.cantidadPorAsunto(mailpit, "Configuración de Smart Parking completada"));
        List<String> bienvenidas = MailpitApiCliente.textosPorAsunto(
                mailpit, "Configuración de Smart Parking completada", correoAnterior);
        assertEquals(2, bienvenidas.size(), "Mailpit debe conservar la bienvenida original y la nueva.");
        assertTrue(bienvenidas.stream().anyMatch(
                        cuerpo -> cuerpo.contains("Estacionamiento del nuevo propietario")),
                "La nueva bienvenida debe reflejar la configuración final.");
        bienvenidas.forEach(cuerpo -> verificarCorreoSinSecretos(
                cuerpo, claveAccesoNueva, claveAdministrativaNueva, grantRecuperado));

        HttpResponse<String> repeticionFinalizacion = api.postCompletar(
                configuracionNueva, claveFinalizacion, grantRecuperado);
        assertEquals(200, repeticionFinalizacion.statusCode(), "El retry de finalización debe ser idempotente.");
        assertEquals(numero(resultadoCompleto, "revision"), numero(leerJson(repeticionFinalizacion.body()), "revision"));
        assertEquals(3, MailpitApiCliente.cantidadMensajes(mailpit),
                "El retry de finalización no debe duplicar la bienvenida.");

        HttpResponse<String> inicioSesionNuevo = api.postJson(
                SESION,
                Map.of("correo", correoAnterior, "contrasena", claveAccesoNueva),
                Map.of(CSRF, csrfAnonimo));
        assertEquals(200, inicioSesionNuevo.statusCode(), "El correo anterior debe poder reutilizarse.");
        JsonNode sesionNueva = leerJson(inicioSesionNuevo.body());
        assertTrue(sesionNueva.path("autenticada").asBoolean());
        assertEquals(correoAnterior, texto(sesionNueva, "correo"));
        api.csrf(texto(sesionNueva, "csrfToken"));
        HttpResponse<String> panelNuevo = api.get("/api/v1/panel");
        assertEquals(200, panelNuevo.statusCode());
        assertEquals("Estacionamiento del nuevo propietario",
                texto(leerJson(panelNuevo.body()).path("estacionamiento"), "nombre"));
        verificarSinSecretos(panelNuevo.body(), claveAccesoNueva, claveAdministrativaNueva, grantRecuperado);

        HttpResponse<String> logoutSinCsrf = api.deleteSinCsrf(SESION);
        assertEquals(403, logoutSinCsrf.statusCode(), "El logout debe exigir CSRF.");
        assertEquals(200, api.get("/api/v1/panel").statusCode(),
                "Un logout rechazado por CSRF debe conservar la sesión activa.");
        HttpResponse<String> cierreSesion = api.deleteConCsrf(SESION);
        assertEquals(200, cierreSesion.statusCode(), "El propietario debe poder cerrar su sesión con CSRF.");
        assertFalse(leerJson(cierreSesion.body()).path("autenticada").asBoolean(),
                "El logout debe devolver una sesión anónima.");
        HttpResponse<String> panelTrasLogout = api.get("/api/v1/panel");
        assertEquals(401, panelTrasLogout.statusCode(), "La sesión cerrada no debe volver a consultar el panel.");

        ApiCliente clienteSinSesion = new ApiCliente(base);
        String csrfSinSesion = clienteSinSesion.obtenerCsrf(false);
        HttpResponse<String> credencialAnterior = clienteSinSesion.postJson(
                SESION,
                Map.of("correo", correoAnterior, "contrasena", claveAccesoAnterior),
                Map.of(CSRF, csrfSinSesion));
        assertEquals(401, credencialAnterior.statusCode(),
                "La contraseña del propietario sustituido no debe autenticar.");
        verificarSinSecretos(credencialAnterior.body(), claveAccesoAnterior);
    }
}
