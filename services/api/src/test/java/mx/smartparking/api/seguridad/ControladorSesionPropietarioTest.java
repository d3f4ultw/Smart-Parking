package mx.smartparking.api.seguridad;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.web.csrf.CsrfToken;

@ExtendWith(MockitoExtension.class)
class ControladorSesionPropietarioTest extends ControladorSesionPropietarioTestSupport {

    @Test
    void loginIncorrectoDevuelveMensajeGenericoYNoRegistraSesion() throws Exception {
        when(administradorAutenticacion.authenticate(any(Authentication.class)))
                .thenThrow(new BadCredentialsException("usuario o clave secretos"));
        MockHttpServletRequest solicitud = nuevaSolicitudConCsrf();

        ResponseEntity<?> resultado = iniciarSesion(solicitud, "clave-incorrecta");

        assertEquals(401, resultado.getStatusCode().value());
        String respuesta = resultado.getBody().toString();
        assertTrue(respuesta.contains("Correo o contraseña no válidos."));
        assertTrue(respuesta.contains("CREDENCIALES_NO_VALIDAS"));
        assertFalse(respuesta.contains("usuario o clave secretos"));
        assertFalse(respuesta.contains("clave-incorrecta"));
        assertFalse(gestorSesiones.estaRegistrada(solicitud.getSession(false).getId(), 13L));
    }

    @Test
    void loginSinDuenoUsaElMismoRechazoGenerico() throws Exception {
        when(administradorAutenticacion.authenticate(any(Authentication.class)))
                .thenThrow(new BadCredentialsException("no hay dueño configurado"));

        ResponseEntity<?> resultado = iniciarSesion(nuevaSolicitudConCsrf(), CONTRASENA);

        assertEquals(401, resultado.getStatusCode().value());
        assertTrue(resultado.getBody().toString().contains("CREDENCIALES_NO_VALIDAS"));
        assertFalse(resultado.getBody().toString().contains("no hay dueño"));
    }

    @Test
    void loginNoAplicaLimiteDeLongitudUtf16AContrasena() throws Exception {
        String larga = "á".repeat(512);
        when(administradorAutenticacion.authenticate(any(Authentication.class)))
                .thenThrow(new BadCredentialsException("incorrecta"));

        ResponseEntity<?> resultado = iniciarSesion(nuevaSolicitudConCsrf(), larga);

        assertEquals(401, resultado.getStatusCode().value());
        verify(administradorAutenticacion).authenticate(any(Authentication.class));
    }

    @Test
    void loginCorrectoRotaLaSesionYElTokenCsrf() throws Exception {
        MockHttpServletRequest solicitud = nuevaSolicitudConCsrf();
        MockHttpSession sesion = (MockHttpSession) solicitud.getSession(false);
        String idAnterior = sesion.getId();
        String tokenAnterior = repositorioCsrf.loadToken(solicitud).getToken();
        gestorSesiones.registrar(sesion, 13L);
        Authentication autenticacion = UsernamePasswordAuthenticationToken.authenticated(
                new PrincipalPropietario(13L, CORREO), null, List.of());
        when(administradorAutenticacion.authenticate(any(Authentication.class))).thenReturn(autenticacion);

        ResponseEntity<?> resultado = iniciarSesion(solicitud, CONTRASENA);

        assertEquals(200, resultado.getStatusCode().value());
        assertNotEquals(idAnterior, sesion.getId());
        assertFalse(gestorSesiones.estaRegistrada(idAnterior, 13L));
        assertTrue(gestorSesiones.estaRegistrada(sesion.getId(), 13L));
        CsrfToken tokenNuevo = repositorioCsrf.loadToken(solicitud);
        assertNotNull(tokenNuevo);
        assertNotEquals(tokenAnterior, tokenNuevo.getToken());
        verify(repositorioContexto).saveContext(any(), any(), any());
        verify(administradorAutenticacion).authenticate(any(Authentication.class));
    }

    @Test
    void loginOperadorRevalidaElegibilidadAntesDeRegistrarLaSesion() throws Exception {
        UUID cuentaId = UUID.randomUUID();
        PrincipalPropietario principal = new PrincipalPropietario(
                cuentaId, RolCuenta.OPERADOR, 4L, 0L, CORREO_OPERADOR);
        Authentication autenticacion = UsernamePasswordAuthenticationToken.authenticated(
                principal, null, List.of(new org.springframework.security.core.authority.SimpleGrantedAuthority(
                        "ROLE_OPERADOR")));
        when(administradorAutenticacion.authenticate(any(Authentication.class))).thenReturn(autenticacion);
        when(cuentas.sesionVigente(cuentaId, 4L, "OPERADOR", 0L)).thenReturn(true);
        MockHttpServletRequest solicitud = nuevaSolicitudConCsrf();
        MockHttpSession sesion = (MockHttpSession) solicitud.getSession(false);
        String idAnterior = sesion.getId();

        ResponseEntity<?> resultado = iniciarSesion(solicitud, CORREO_OPERADOR, CONTRASENA);

        assertEquals(200, resultado.getStatusCode().value());
        assertTrue(resultado.getBody().toString().contains("rol=OPERADOR"));
        assertNotEquals(idAnterior, sesion.getId());
        assertTrue(gestorSesiones.estaRegistrada(sesion.getId(), 0L));
        verify(cuentas).sesionVigente(cuentaId, 4L, "OPERADOR", 0L);
        verify(repositorioContexto).saveContext(any(), any(), any());
    }

    @Test
    void operadorQuePierdeElegibilidadAntesDeCrearSesionRecibeRechazoGenerico() throws Exception {
        UUID cuentaId = UUID.randomUUID();
        PrincipalPropietario principal = new PrincipalPropietario(
                cuentaId, RolCuenta.OPERADOR, 4L, 0L, CORREO_OPERADOR);
        Authentication autenticacion = UsernamePasswordAuthenticationToken.authenticated(
                principal, null, List.of(new org.springframework.security.core.authority.SimpleGrantedAuthority(
                        "ROLE_OPERADOR")));
        when(administradorAutenticacion.authenticate(any(Authentication.class))).thenReturn(autenticacion);
        when(cuentas.sesionVigente(cuentaId, 4L, "OPERADOR", 0L)).thenReturn(false);
        MockHttpServletRequest solicitud = nuevaSolicitudConCsrf();
        MockHttpSession sesion = (MockHttpSession) solicitud.getSession(false);
        String idAnterior = sesion.getId();

        ResponseEntity<?> resultado = iniciarSesion(solicitud, CORREO_OPERADOR, CONTRASENA);

        assertEquals(401, resultado.getStatusCode().value());
        assertTrue(resultado.getBody().toString().contains("CREDENCIALES_NO_VALIDAS"));
        assertEquals(idAnterior, sesion.getId());
        assertFalse(gestorSesiones.estaRegistrada(sesion.getId(), 0L));
        verify(repositorioContexto, never()).saveContext(any(), any(), any());
    }

    @Test
    void falloDeBaseAlRevalidarOperadorResponde503SinCrearSesion() throws Exception {
        UUID cuentaId = UUID.randomUUID();
        PrincipalPropietario principal = new PrincipalPropietario(
                cuentaId, RolCuenta.OPERADOR, 4L, 0L, CORREO_OPERADOR);
        Authentication autenticacion = UsernamePasswordAuthenticationToken.authenticated(
                principal, null, List.of(new org.springframework.security.core.authority.SimpleGrantedAuthority(
                        "ROLE_OPERADOR")));
        when(administradorAutenticacion.authenticate(any(Authentication.class))).thenReturn(autenticacion);
        when(cuentas.sesionVigente(cuentaId, 4L, "OPERADOR", 0L))
                .thenThrow(new DataAccessResourceFailureException("detalle-interno-secreto"));
        MockHttpServletRequest solicitud = nuevaSolicitudConCsrf();
        MockHttpSession sesion = (MockHttpSession) solicitud.getSession(false);
        String idAnterior = sesion.getId();

        ResponseEntity<?> resultado = iniciarSesion(solicitud, CORREO_OPERADOR, CONTRASENA);

        assertEquals(503, resultado.getStatusCode().value());
        assertFalse(resultado.getBody().toString().contains("detalle-interno-secreto"));
        assertEquals(idAnterior, sesion.getId());
        verify(repositorioContexto, never()).saveContext(any(), any(), any());
    }

    @Test
    void quintoFalloBloqueaIntentosSiguientesSinConsultarAutenticador() throws Exception {
        when(administradorAutenticacion.authenticate(any(Authentication.class)))
                .thenThrow(new BadCredentialsException("credenciales inválidas"));

        for (int intento = 0; intento < 6; intento++) {
            MockHttpServletRequest solicitud = nuevaSolicitudConCsrf();
            ResponseEntity<?> resultado = iniciarSesion(solicitud, "incorrecta");
            assertEquals(401, resultado.getStatusCode().value());
        }

        verify(administradorAutenticacion, times(5)).authenticate(any(Authentication.class));
    }
}
