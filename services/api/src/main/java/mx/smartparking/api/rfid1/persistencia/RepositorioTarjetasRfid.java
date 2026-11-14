package mx.smartparking.api.rfid1.persistencia;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/** Define cómo consultar las tarjetas registradas y cancelar una asociación de forma permanente. */
public interface RepositorioTarjetasRfid {

    /** Devuelve candidatos coincidentes, incluso no elegibles, con datos para calcular su elegibilidad y motivo. */
    List<CandidatoRfid1Persistido> buscarPersonas(String tipoEntidad, String busqueda, int limite);

    List<TarjetaRfid1Persistida> listarTarjetas(
            String tipoEntidad, String estado, String busqueda, int offset, int limite);

    /** Permite ocultar los números de tarjeta y limitar su búsqueda según los permisos de quien consulta. */
    default List<TarjetaRfid1Persistida> listarTarjetas(
            String tipoEntidad, String estado, String busqueda, int offset, int limite, boolean incluirUid) {
        return listarTarjetas(tipoEntidad, estado, busqueda, offset, limite);
    }

    long contarTarjetas(String tipoEntidad, String estado, String busqueda);

    /** Cuenta los resultados usando solo los datos que la persona autorizada puede buscar. */
    default long contarTarjetas(String tipoEntidad, String estado, String busqueda, boolean incluirUid) {
        return contarTarjetas(tipoEntidad, estado, busqueda);
    }

    Optional<TarjetaRfid1Persistida> buscarTarjeta(long asociacionId);

    /** Permite mostrar el detalle de una tarjeta al operador sin revelar su número de identificación. */
    default Optional<TarjetaRfid1Persistida> buscarTarjeta(long asociacionId, boolean incluirUid) {
        return buscarTarjeta(asociacionId);
    }

    /**
     * Evita cambios simultáneos al cancelar una tarjeta, protegiendo primero los datos de la persona y
     * después los de la tarjeta.
     */
    ResultadoCancelacionTarjetaRfid1 cancelarTarjeta(long asociacionId, Instant ahora);

    /** Datos del candidato para explicar su elegibilidad; {@code estadoMembresia} es {@code null} para empleados. */
    record CandidatoRfid1Persistido(
            String tipoEntidad,
            String codigoPersona,
            String nombreCompleto,
            String estadoAdministrativo,
            boolean tieneTarjetaActiva,
            String estadoMembresia) {

        public CandidatoRfid1Persistido(
                String tipoEntidad,
                String codigoPersona,
                String nombreCompleto,
                String estadoAdministrativo,
                boolean tieneTarjetaActiva) {
            this(tipoEntidad, codigoPersona, nombreCompleto, estadoAdministrativo, tieneTarjetaActiva, null);
        }
    }

    record TarjetaRfid1Persistida(
            long asociacionId,
            String uidCanonico,
            String tipoEntidad,
            String codigoPersona,
            String nombreCompleto,
            String estado,
            Instant asociadaEn,
            Instant canceladaEn) {
    }

    record ResultadoCancelacionTarjetaRfid1(String estado, String codigoError, boolean repetida) {
    }
}
