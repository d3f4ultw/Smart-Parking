package mx.smartparking.api.rfid1.persistencia;

import java.time.Instant;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

/** Define cómo guardar y consultar las lecturas necesarias para asociar una tarjeta a una persona. */
public interface RepositorioRfid1 {

    int expirarCapturasVencidas(Instant ahora);

    int purgarCapturasTerminalesAnterioresA(Instant limite);

    Optional<DestinoRfid1Persistido> resolverDestino(String tipoEntidad, String codigoPersona);

    boolean destinoTieneTarjeta(DestinoRfid1Persistido destino);

    Optional<CapturaRfid1Persistida> buscarPorIdempotencia(
            UUID propietarioId, String claveHash, String huellaSesion);

    Optional<CapturaRfid1Persistida> buscarActivaDePropietario(
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion,
            Instant ahora);

    Optional<CapturaRfid1Persistida> buscarActivaParaDispositivo(Instant ahora);

    Optional<CapturaRfid1Persistida> buscarPorPropietario(
            String capturaId,
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion);

    boolean insertarCaptura(NuevaCapturaRfid1 nueva);

    /**
     * Mantiene protegida la lectura mientras se comprueba al propietario y se registra que comenzó la
     * búsqueda.
     */
    ResultadoEstadoCaptura marcarEscaneando(String capturaId, Instant ahora);

    /** Cancela una lectura activa mientras se comprueba que el propietario aún puede realizar la acción. */
    ResultadoEstadoCaptura cancelar(
            String capturaId,
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion,
            Instant ahora);

    /** Guarda la lectura, la asociación y el resultado como parte de la misma operación. */
    ResultadoLecturaRfid1 completarLectura(
            String capturaId,
            String requestId,
            String uidCanonico,
            String huellaUid,
            Instant ahora);

    Optional<VistaPreviaRfid1Persistida> consultarVistaPrevia(
            String capturaId,
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion,
            Instant ahora);

    ResultadoConfirmacionRfid1 confirmarCaptura(
            String capturaId,
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion,
            String hashClaveConfirmacion,
            Instant ahora);

    int invalidarPorSesion(String huellaSesion, Instant ahora);

    int invalidarSesionesAusentes(Set<String> huellasActivas, Instant ahora);

    record DestinoRfid1Persistido(
            String tipoEntidad,
            String codigoPersona,
            UUID clienteId,
            Long empleadoId,
            boolean activo,
            String estadoMembresia) {

        public DestinoRfid1Persistido(
                String tipoEntidad,
                String codigoPersona,
                UUID clienteId,
                Long empleadoId,
                boolean activo) {
            this(tipoEntidad, codigoPersona, clienteId, empleadoId, activo, null);
        }

        public boolean sinMembresia() {
            return clienteId != null && "SIN_MEMBRESIA".equals(estadoMembresia);
        }
    }

    record NuevaCapturaRfid1(
            String capturaId,
            String tipoEntidad,
            String codigoPersona,
            UUID clienteId,
            Long empleadoId,
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion,
            String claveIdempotenciaHash,
            String huellaSolicitud,
            Instant creadaEn,
            Instant venceEn) {
    }

    record CapturaRfid1Persistida(
            String capturaId,
            String tipoEntidad,
            String codigoPersona,
            UUID clienteId,
            Long empleadoId,
            UUID propietarioId,
            long revisionAcceso,
            long revisionPropietario,
            String huellaSesion,
            String claveIdempotenciaHash,
            String huellaSolicitud,
            String requestId,
            String huellaUid,
            String estado,
            String resultado,
            String codigoError,
            Instant creadaEn,
            Instant venceEn,
            Instant terminadaEn,
            Instant previsualizadaEn,
            Instant confirmacionVenceEn,
            String hashClaveConfirmacion,
            String codigoConfirmacion,
            Long asociacionConfirmadaId) {
    }

    record ResultadoEstadoCaptura(String estado, String codigoError) {
    }

    record ResultadoLecturaRfid1(String estado, String resultado, String codigoError, boolean repetida) {
    }

    record VistaPreviaRfid1Persistida(
            String uidCanonico,
            Instant previsualizadaEn,
            Instant confirmacionVenceEn) {
    }

    record ResultadoConfirmacionRfid1(
            String estado,
            Long asociacionId,
            String codigoError,
            boolean repetida) {
    }
}
