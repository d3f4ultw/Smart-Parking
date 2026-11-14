package mx.smartparking.api.clientes.administracion.modelo;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.time.Instant;

/** Presenta únicamente el estado y las fechas guardadas de la membresía. */
@JsonInclude(JsonInclude.Include.ALWAYS)
public record DetalleMembresiaAdministracion(
        PlanMembresiaAdministracion plan,
        Instant periodoInicio,
        Instant periodoFin,
        Instant siguienteCobroEn,
        boolean cancelacionAlFinal) {
}
