package mx.smartparking.api.persistencia;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/** Carga consultas SQL desde los recursos incluidos en el classpath de la API. */
public final class CargadorSql {

    private CargadorSql() {
    }

    /**
     * Lee un recurso bajo {@code sql/} como texto UTF-8.
     *
     * @param rutaRelativa ruta relativa dentro de {@code sql/}
     * @return contenido completo del recurso
     * @throws IllegalStateException si el recurso no existe o no se puede leer
     */
    public static String cargar(String rutaRelativa) {
        String ruta = "sql/" + rutaRelativa;
        try (InputStream recurso = CargadorSql.class.getClassLoader().getResourceAsStream(ruta)) {
            if (recurso == null) {
                throw new IllegalStateException("No se encontró el recurso SQL requerido: " + ruta);
            }
            return new String(recurso.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException excepcion) {
            throw new IllegalStateException("No se pudo leer el recurso SQL requerido: " + ruta, excepcion);
        }
    }
}
