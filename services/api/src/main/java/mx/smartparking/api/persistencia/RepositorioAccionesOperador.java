package mx.smartparking.api.persistencia;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.activacion.EstadoEnvioInvitacion;

/** Guarda las invitaciones, recuperaciones y resultados necesarios para reconocer solicitudes repetidas. */
public interface RepositorioAccionesOperador {

    Optional<InvitacionOperadorPersistida> consultarInvitacion(UUID operadorId);

    Optional<InvitacionOperadorPersistida> bloquearInvitacion(UUID operadorId);

    Optional<RecuperacionContrasenaOperadorPersistida> consultarRecuperacion(UUID operadorId);

    Optional<RecuperacionContrasenaOperadorPersistida> bloquearRecuperacion(UUID operadorId);

    Optional<RecuperacionContrasenaOperadorPersistida> buscarRecuperacionPorHash(String tokenHash);

    Optional<AccionOperadorPersistida> buscarAccion(UUID operadorId, String operacion, String claveHash);

    Optional<AccionOperadorPersistida> bloquearAccion(UUID operadorId, String operacion, String claveHash);

    void bloquearAcciones(UUID operadorId);

    int contarAcciones(UUID operadorId, String operacion, Instant desde);

    Optional<Instant> ultimaAccion(UUID operadorId, String operacion);

    Optional<Instant> primeraAccion(UUID operadorId, List<String> operaciones, Instant desde);

    boolean insertarAccion(UUID operadorId, String operacion, String claveHash, Instant creadaEn,
                           EstadoEnvioInvitacion estadoEnvio, Long revisionAcceso, Instant venceEn);

    boolean reemplazarInvitacion(UUID operadorId, String tokenHashEsperado, String tokenHashNuevo,
                                 Instant generadaEn, Instant venceEn, Instant intentoIniciadoEn);

    boolean prepararInvitacion(UUID operadorId, String tokenHashNuevo, Instant generadaEn,
                               Instant venceEn, Instant intentoIniciadoEn);

    boolean crearRecuperacion(UUID operadorId, String tokenHash, Instant generadaEn,
                              Instant venceEn, Instant intentoIniciadoEn);

    boolean consumirRecuperacion(UUID operadorId, String tokenHash, Instant ahora);

    boolean actualizarContrasena(UUID operadorId, long revisionEsperada, String hashContrasena, Instant ahora);

    void invalidarInvitacion(UUID operadorId, Instant ahora);

    void invalidarRecuperacion(UUID operadorId, Instant ahora);

    boolean actualizarEstadoInvitacion(UUID operadorId, String tokenHash, EstadoEnvioInvitacion estado);

    boolean actualizarEstadoRecuperacion(UUID operadorId, String tokenHash, EstadoEnvioInvitacion estado);

    void actualizarEstadoAccion(UUID operadorId, String operacion, String claveHash, EstadoEnvioInvitacion estado);
}
