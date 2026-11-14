package mx.smartparking.api.integracion.unificacion;

import mx.smartparking.fixture.SandboxFixtureControlador;
import mx.smartparking.api.seguridad.GestorSesionesPropietario;
import mx.smartparking.api.persistencia.RepositorioCuentas;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.web.context.SecurityContextRepository;
import org.springframework.transaction.PlatformTransactionManager;

/** Registra el único controlador de fixtures en el proceso de aceptación. */
@TestConfiguration(proxyBeanMethods = false)
@Profile("test")
public class SandboxFixtureConfiguracion {

    @Bean
    SandboxFixtureControlador sandboxFixtureControlador(
            JdbcTemplate jdbc,
            RepositorioCuentas cuentas,
            GestorSesionesPropietario sesiones,
            SecurityContextRepository contexto,
            PlatformTransactionManager administradorTransacciones,
            @Value("${SPNEXT_TEST_FIXTURE_NONCE:}") String nonceConfigurado) {
        return new SandboxFixtureControlador(
                jdbc, cuentas, sesiones, contexto, administradorTransacciones, nonceConfigurado);
    }
}
