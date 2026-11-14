package mx.smartparking.api.integracion.unificacion;

import mx.smartparking.api.AplicacionApi;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.context.annotation.ComponentScan.Filter;
import org.springframework.context.annotation.FilterType;
import org.springframework.context.annotation.Import;

/** Arranca el mismo contexto de API con fixtures cargados solo en el classpath de pruebas. */
@SpringBootConfiguration
@EnableAutoConfiguration
@ComponentScan(
        basePackages = "mx.smartparking.api",
        excludeFilters = {
            @Filter(type = FilterType.ANNOTATION, classes = TestConfiguration.class),
            @Filter(type = FilterType.ASSIGNABLE_TYPE, classes = {AplicacionApi.class, SandboxTestApplication.class})
        })
@Import(SandboxFixtureConfiguracion.class)
public class SandboxTestApplication {

    public static void main(String[] argumentos) {
        SpringApplication.run(SandboxTestApplication.class, argumentos);
    }
}
