package mx.smartparking.api.persistencia;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.configuracion.DatosConfiguracion;
import mx.smartparking.api.configuracion.HorarioConfiguracion;
import mx.smartparking.api.configuracion.TipoEstacionamiento;

/** Define cómo consultar y guardar la única configuración del estacionamiento. */
public interface RepositorioConfiguracion {

    ConfiguracionPersistida obtener();

    ConfiguracionPersistida bloquear();

    Optional<ConfiguracionPersistida> buscar();

    void configurarInicial(
            DatosConfiguracion datos,
            String hashAdministrativa,
            UUID estacionamientoId,
            UUID duenoCuentaId,
            long revision,
            long revisionPropietario,
            UUID operacionId,
            String hashClaveIdempotencia);

    void renombrar(
            String nombre,
            long revision,
            UUID operacionId,
            String hashClaveIdempotencia);

    void actualizarDatosEstacionamiento(
            TipoEstacionamiento tipo,
            HorarioConfiguracion horario,
            long revision,
            UUID operacionId,
            String hashClaveIdempotencia);

    void iniciarTransferencia(
            UUID transferId,
            String hashGrant,
            Instant venceEn,
            String hashRecuperacion,
            long revision,
            long revisionPropietario,
            UUID operacionId,
            String hashClaveIdempotencia);

    void reemitirGrant(String hashGrant, Instant venceEn, long revision);

    void completarTransferencia(
            DatosConfiguracion datos,
            String hashAdministrativa,
            UUID duenoCuentaId,
            long revision,
            long revisionPropietario,
            UUID operacionId,
            String hashClaveIdempotencia);

    void actualizarEstadoAviso(UUID operacionId, TipoAviso tipo, String estado);

    enum TipoAviso {
        TRANSFERENCIA,
        BIENVENIDA
    }
}
