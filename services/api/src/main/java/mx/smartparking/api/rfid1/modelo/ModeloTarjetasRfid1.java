package mx.smartparking.api.rfid1.modelo;

import java.time.Instant;
import java.util.List;
import mx.smartparking.api.configuracion.TipoEstacionamiento;
import mx.smartparking.api.rfid1.persistencia.RepositorioTarjetasRfid.CandidatoRfid1Persistido;
import mx.smartparking.api.rfid1.persistencia.RepositorioTarjetasRfid.TarjetaRfid1Persistida;

/**
 * Reúne los datos privados de las tarjetas que solo puede consultar el personal autorizado;
 * las respuestas no deben guardarse en el navegador.
 */
public final class ModeloTarjetasRfid1 {

    private ModeloTarjetasRfid1() {
    }

    public record CandidatoPersona(
            String tipoEntidad,
            String codigoPersona,
            String nombreCompleto,
            String estadoAdministrativo,
            boolean elegible,
            String motivoNoElegible) {

        /**
         * Mantiene los criterios administrativos y de tarjeta activa; en clientes, excluye solo el estado exacto
         * {@code SIN_MEMBRESIA}.
         */
        public static CandidatoPersona desde(CandidatoRfid1Persistido candidato) {
            boolean activo = switch (candidato.tipoEntidad()) {
                case "CLIENTE" -> "ACTIVA".equals(candidato.estadoAdministrativo());
                case "EMPLEADO" -> "ACTIVO".equals(candidato.estadoAdministrativo());
                default -> false;
            };
            boolean sinMembresia = "CLIENTE".equals(candidato.tipoEntidad())
                    && "SIN_MEMBRESIA".equals(candidato.estadoMembresia());
            boolean elegible = activo && !candidato.tieneTarjetaActiva() && !sinMembresia;
            String motivo = !activo
                    ? "PERSONA_INACTIVA"
                    : candidato.tieneTarjetaActiva() ? "PERSONA_CON_TARJETA"
                            : sinMembresia ? "CLIENTE_SIN_MEMBRESIA" : null;
            return new CandidatoPersona(
                    candidato.tipoEntidad(), candidato.codigoPersona(), candidato.nombreCompleto(),
                    candidato.estadoAdministrativo(), elegible, motivo);
        }
    }

    public record Modalidad(TipoEstacionamiento tipoEstacionamiento) {
    }

    public record Tarjeta(
            long asociacionId,
            String uid,
            String tipoEntidad,
            String codigoPersona,
            String nombreCompleto,
            String estado,
            Instant asociadaEn,
            Instant canceladaEn) {

        public static Tarjeta desde(TarjetaRfid1Persistida tarjeta) {
            return desde(tarjeta, true);
        }

        public static Tarjeta desde(TarjetaRfid1Persistida tarjeta, boolean incluirUid) {
            return new Tarjeta(
                    tarjeta.asociacionId(), incluirUid ? tarjeta.uidCanonico() : null,
                    tarjeta.tipoEntidad(), tarjeta.codigoPersona(),
                    tarjeta.nombreCompleto(), tarjeta.estado(), tarjeta.asociadaEn(), tarjeta.canceladaEn());
        }
    }

    public record Pagina(List<Tarjeta> items, int pagina, int tamano, long total, int totalPaginas) {
        public Pagina {
            items = List.copyOf(items);
        }
    }

    public record VistaPrevia(String uid, Instant previsualizadaEn, Instant confirmacionVenceEn) {
    }

    public record Confirmacion(String capturaId, long asociacionId, String estado, String resultado) {
    }

    public record Cancelacion(long asociacionId, String estado) {
    }
}
