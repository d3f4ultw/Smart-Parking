package mx.smartparking.ownerconsole.servicio;

import java.time.LocalTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.format.ResolverStyle;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import mx.smartparking.ownerconsole.modelo.BorradorConfiguracion;
import mx.smartparking.ownerconsole.modelo.PasoConfiguracion;

/** Valida cada vista antes de permitir que el usuario avance. */
public final class ValidadorConfiguracion {

    private static final Pattern CORREO = Pattern.compile("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$");
    private static final DateTimeFormatter FORMATO_HORA = DateTimeFormatter.ofPattern("HH:mm")
            .withResolverStyle(ResolverStyle.STRICT);
    private static final Set<String> TIPOS = Set.of("PUBLICO", "PRIVADO", "MIXTO");

    /** Comprueba solo los campos visibles en la vista actual. */
    public Map<String, String> validar(PasoConfiguracion paso, BorradorConfiguracion borrador) {
        Map<String, String> errores = new LinkedHashMap<>();
        switch (paso) {
            case IDENTIDAD -> validarIdentidad(borrador, errores);
            case ACCESO -> validarAcceso(borrador, errores);
            case ADMINISTRACION -> validarAdministracion(borrador, errores);
            case ESTACIONAMIENTO -> validarEstacionamiento(borrador, errores);
            case HORARIO -> validarHorario(borrador, errores);
            case REVISION -> {
                // La última vista solo confirma los datos ya validados.
            }
        }
        return Collections.unmodifiableMap(new LinkedHashMap<>(errores));
    }

    private void validarIdentidad(BorradorConfiguracion borrador, Map<String, String> errores) {
        requerido(borrador.nombres(), "nombres", "Ingresa tu nombre.", errores);
        requerido(
                borrador.primerApellido(),
                "primerApellido",
                "Ingresa tu primer apellido.",
                80,
                errores);
        String segundoApellido = borrarEspacios(borrador.segundoApellido());
        if (segundoApellido.length() > 80) {
            errores.put("segundoApellido", "Escribe un apellido más corto.");
        }
    }

    private void validarAcceso(BorradorConfiguracion borrador, Map<String, String> errores) {
        String correo = borrarEspacios(borrador.correo());
        if (correo.isEmpty() || correo.length() > 254 || !CORREO.matcher(correo).matches()) {
            errores.put("correo", "Ingresa un correo válido.");
        }
        char[] contrasena = borrador.copiarContrasenaAcceso();
        try {
            validarLargo(contrasena, "contrasenaAcceso", errores);
        } finally {
            borrar(contrasena);
        }
    }

    private void validarAdministracion(BorradorConfiguracion borrador, Map<String, String> errores) {
        char[] contrasenaAcceso = borrador.copiarContrasenaAcceso();
        char[] contrasenaAdministrativa = borrador.copiarContrasenaAdministrativa();
        char[] confirmacion = borrador.copiarConfirmacionAdministrativa();
        try {
            validarLargo(contrasenaAdministrativa, "contrasenaAdministrativa", errores);
            if (!Arrays.equals(contrasenaAdministrativa, confirmacion)) {
                errores.put("confirmacionAdministrativa", "Las contraseñas no coinciden.");
            }
            if (Arrays.equals(contrasenaAcceso, contrasenaAdministrativa)) {
                errores.put("contrasenaAdministrativa", "Elige otra contraseña.");
            }
        } finally {
            borrar(contrasenaAcceso);
            borrar(contrasenaAdministrativa);
            borrar(confirmacion);
        }
    }

    private void validarEstacionamiento(BorradorConfiguracion borrador, Map<String, String> errores) {
        String nombre = borrarEspacios(borrador.nombreEstacionamiento());
        if (nombre.isEmpty()) {
            errores.put("nombreEstacionamiento", "Escribe el nombre del estacionamiento.");
        } else if (nombre.length() > 120) {
            errores.put("nombreEstacionamiento", "Escribe un nombre más corto.");
        }
        if (!TIPOS.contains(borrador.tipoEstacionamiento())) {
            errores.put("tipoEstacionamiento", "Selecciona un tipo de estacionamiento.");
        }
    }

    private void validarHorario(BorradorConfiguracion borrador, Map<String, String> errores) {
        boolean continuo = "CONTINUO_24_7".equals(borrador.modoHorario());
        boolean intervalo = "INTERVALO_DIARIO".equals(borrador.modoHorario());
        if (!continuo && !intervalo) {
            errores.put("modoHorario", "Selecciona un horario de atención.");
        }
        if (borrador.zonaHoraria() == null || !ZoneId.getAvailableZoneIds().contains(borrador.zonaHoraria())) {
            errores.put("zonaHoraria", "Selecciona una zona horaria.");
        }
        if (intervalo) {
            LocalTime apertura = parsearHora(
                    borrador.horaApertura(), "horaApertura", "Selecciona una hora de apertura.", errores);
            LocalTime cierre = parsearHora(
                    borrador.horaCierre(), "horaCierre", "Selecciona una hora de cierre.", errores);
            if (apertura != null && apertura.equals(cierre)) {
                errores.put("horaCierre", "La hora de cierre debe ser distinta de la apertura.");
            }
        }
    }

    private LocalTime parsearHora(String valor, String campo, String mensaje, Map<String, String> errores) {
        try {
            if (valor == null || !valor.matches("(?:[01][0-9]|2[0-3]):[0-5][0-9]")) {
                throw new IllegalArgumentException();
            }
            return LocalTime.parse(valor, FORMATO_HORA);
        } catch (RuntimeException error) {
            errores.put(campo, mensaje);
            return null;
        }
    }

    private void validarLargo(char[] secreto, String campo, Map<String, String> errores) {
        int largo = Character.codePointCount(secreto, 0, secreto.length);
        if (largo < 10) {
            errores.put(campo, "Elige una contraseña más larga.");
        }
    }

    private void requerido(String valor, String campo, String mensaje, Map<String, String> errores) {
        requerido(valor, campo, mensaje, 120, errores);
    }

    private void requerido(String valor, String campo, String mensaje, int maximo, Map<String, String> errores) {
        if (valor == null || valor.isBlank()) {
            errores.put(campo, mensaje);
        } else if (valor.length() > maximo) {
            errores.put(campo, "Escribe un texto más corto.");
        }
    }

    private String borrarEspacios(String valor) {
        return valor == null ? "" : valor.trim();
    }

    private void borrar(char[] valor) {
        Arrays.fill(valor, '\0');
    }
}
