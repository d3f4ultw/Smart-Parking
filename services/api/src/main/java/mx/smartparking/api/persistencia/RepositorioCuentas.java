package mx.smartparking.api.persistencia;

import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.configuracion.DatosConfiguracion;

/** Define cómo consultar y guardar los datos de identidad y acceso de las cuentas. */
public interface RepositorioCuentas {

    UUID crearDueno(DatosConfiguracion datos, String hashContrasena);

    UUID crearCliente(
            String nombres,
            String primerApellido,
            String segundoApellido,
            String correoNormalizado,
            String hashContrasena);

    boolean actualizarContrasenaCliente(UUID cuentaId, long revisionEsperada, String hashContrasena);

    Optional<CuentaPersistida> buscarActivaPorCorreo(String correoNormalizado);

    Optional<CuentaPersistida> obtener(UUID cuentaId);

    Optional<CuentaPersistida> duenoActual();

    void desactivar(UUID cuentaId);

    boolean sesionVigente(UUID cuentaId, long revisionAcceso, String rol, long revisionPropietario);
}
