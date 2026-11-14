package mx.smartparking.api.empleados.coordinacion;

import java.util.UUID;
import mx.smartparking.api.seguridad.PrincipalPropietario;

/**
 * Describe las acciones que relacionan a un empleado con su cuenta de operador, como crearla,
 * vincularla o retirar su acceso.
 */
public interface PuertoAdministracionEmpleadoOperador {

    /** crea o reactiva la cuenta de operador asociada al empleado y prepara su invitación. */
    ResultadoAccionEmpleadoOperador promocionar(
            String empleadoId, String ifMatch, String claveIdempotencia, PrincipalPropietario propietario);

    /**
     * crea o reactiva la cuenta de operador y prepara la invitación con el correo disponible
     * @param correo correo opcional; si se omite, se usa el correo del empleado
     */
    ResultadoAccionEmpleadoOperador promocionar(
            String empleadoId, String correo, String ifMatch, String claveIdempotencia,
            PrincipalPropietario propietario);

    /** actualiza el correo del empleado y el de su cuenta de operador vinculada, si existe. */
    ResultadoCambioCorreoEmpleadoOperador cambiarCorreo(
            String empleadoId, String correo, String ifMatch, String claveIdempotencia,
            PrincipalPropietario propietario);

    /** retira el acceso de operador, deja sin efecto sus invitaciones pendientes y cierra sus sesiones. */
    ResultadoAccionEmpleadoOperador desactivarAcceso(
            String empleadoId, String ifMatch, String claveIdempotencia, PrincipalPropietario propietario);

    /**
     * vincula el empleado con una cuenta libre y exige confirmar si se copia un correo
     * @param revisionOperador versión consultada de la cuenta que se quiere vincular
     * @param copiarCorreoOperador confirma copiar el correo de la cuenta cuando el empleado no tiene uno
     */
    ResultadoAccionEmpleadoOperador vincular(
            String empleadoId, UUID operadorId, String revisionOperador, boolean copiarCorreoOperador, String ifMatch,
            String claveIdempotencia, PrincipalPropietario propietario);

    ResultadoAccionEmpleadoOperador cambiarEstadoEmpleado(
            String empleadoId, String estado, String ifMatch, PrincipalPropietario propietario);
}
