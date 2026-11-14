package mx.smartparking.api.persistencia;

import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.operadores.AccionEmpleadoOperadorPersistida;

/** Guarda el resultado de una acción sobre la relación empleado y operador para no repetirla por error. */
public interface RepositorioAccionesEmpleadoOperador {

    boolean reservar(UUID duenoCuentaId, String claveHash, String huella, String operacion, long empleadoId);

    Optional<AccionEmpleadoOperadorPersistida> bloquear(UUID duenoCuentaId, String claveHash);

    void completar(
            UUID duenoCuentaId,
            String claveHash,
            UUID operadorId,
            String estadoOperador,
            long revisionEmpleado,
            String estadoEnvio);

    void actualizarEstadoEnvio(UUID duenoCuentaId, String claveHash, String estadoEnvio);
}
