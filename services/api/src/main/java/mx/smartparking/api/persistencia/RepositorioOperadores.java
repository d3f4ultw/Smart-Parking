package mx.smartparking.api.persistencia;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import mx.smartparking.api.operadores.CuentaOperadorAdministrable;
import mx.smartparking.api.operadores.DatosRegistroOperador;
import mx.smartparking.api.operadores.EstadoCuentaOperador;
import mx.smartparking.api.operadores.Operador;

/** Define cómo guardar un operador sin duplicar solicitudes y consultar su directorio. */
public interface RepositorioOperadores {

    ResultadoPaginaOperadores consultarPagina(
            int paginaSolicitada, int tamanoPagina, String busqueda, EstadoCuentaOperador estado);

    boolean reservarRegistro(UUID duenoCuentaId, String claveHash, String huellaSolicitud);

    Optional<ComprobanteRegistroOperador> buscarComprobante(UUID duenoCuentaId, String claveHash);

    UUID crearOperadorPendiente(UUID operadorId, DatosRegistroOperador datos);

    void completarRegistro(UUID duenoCuentaId, String claveHash, UUID operadorId);

    Optional<Operador> buscarPorId(UUID operadorId);

    Optional<Long> empleadoId(UUID operadorId);

    Optional<CuentaOperadorAdministrable> buscarCuentaVinculada(long empleadoId);

    Optional<CuentaOperadorAdministrable> bloquearCuentaVinculada(long empleadoId);

    UUID crearOperadorVinculado(UUID operadorId, long empleadoId);

    CuentaOperadorAdministrable reactivarCuentaVinculada(
            UUID operadorId, long empleadoId, String correo, String correoNormalizado, long revisionEsperada);

    CuentaOperadorAdministrable actualizarCorreo(
            UUID operadorId, String correo, String correoNormalizado, long revisionEsperada);

    CuentaOperadorAdministrable vincularCuenta(UUID operadorId, long empleadoId, long revisionEsperada);

    boolean correoReservado(String correoNormalizado, UUID excluirCuentaId);

    Optional<CuentaOperadorAdministrable> buscarCuentaAdministrable(UUID operadorId);

    Optional<CuentaOperadorAdministrable> bloquearCuentaAdministrable(UUID operadorId);

    CuentaOperadorAdministrable actualizarEstado(
            UUID operadorId, EstadoCuentaOperador estado, long revisionEsperada, long revisionNueva);

    record ResultadoPaginaOperadores(
            List<Operador> items,
            int pagina,
            long totalRegistros,
            long totalPaginas) {
        public ResultadoPaginaOperadores {
            items = List.copyOf(items);
        }
    }

    record ComprobanteRegistroOperador(String huellaSolicitud, String estado, UUID operadorId) {
    }
}
