package mx.smartparking.api.persistencia;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;

/** Define cómo guardar la invitación, el resultado de su envío y la activación de una cuenta. */
public interface RepositorioActivacionOperador {

    void crearInicial(UUID operadorId, String tokenHash, Instant generadoEn, Instant venceEn);

    Optional<InvitacionOperadorPersistida> buscarPorTokenHash(String tokenHash);

    Optional<Long> empleadoId(UUID operadorId);

    Optional<CuentaActivacionOperador> bloquearCuenta(UUID operadorId);

    Optional<InvitacionOperadorPersistida> bloquearInvitacion(UUID operadorId);

    boolean activar(UUID operadorId, long revisionEsperada, String hashContrasena, Instant ahora);

    boolean consumir(UUID operadorId, String tokenHash, Instant ahora);

    Optional<ResultadoActualizacionEnvio> actualizarResultadoEnvio(
            UUID operadorId, String tokenHashEsperado, EstadoEnvioInvitacion estado);

    record ResultadoActualizacionEnvio(
            EstadoEnvioInvitacion estado, boolean cambioAplicado, boolean cambioVisible) {
    }
}
