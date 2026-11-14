package mx.smartparking.api.rfid1;

import mx.smartparking.api.configuracion.TipoEstacionamiento;

/** Determina qué personas pueden usar tarjetas según el tipo de estacionamiento elegido. */
public final class PoliticaModalidadRfid1 {

    private PoliticaModalidadRfid1() {
    }

    public static boolean permite(TipoEstacionamiento modalidad, String tipoEntidad) {
        if (modalidad == null || tipoEntidad == null) {
            return false;
        }
        return switch (modalidad) {
            case PUBLICO -> "CLIENTE".equals(tipoEntidad);
            case PRIVADO -> "EMPLEADO".equals(tipoEntidad);
            case MIXTO -> "CLIENTE".equals(tipoEntidad) || "EMPLEADO".equals(tipoEntidad);
        };
    }

    /**
     * Indica qué personas se pueden buscar según el tipo de estacionamiento; si el filtro no
     * corresponde, no devuelve un tipo permitido.
     */
    public static String tipoCandidato(TipoEstacionamiento modalidad, String tipoSolicitado) {
        if (modalidad == null || tipoSolicitado == null) {
            return null;
        }
        if ("MIXTO".equals(tipoSolicitado)) {
            return switch (modalidad) {
                case PUBLICO -> "CLIENTE";
                case PRIVADO -> "EMPLEADO";
                case MIXTO -> "MIXTO";
            };
        }
        return permite(modalidad, tipoSolicitado) ? tipoSolicitado : null;
    }
}
