package mx.smartparking.ownerconsole.controlador.configuracion;

import java.util.LinkedHashMap;
import java.util.Map;
import mx.smartparking.ownerconsole.modelo.BorradorConfiguracion;
import mx.smartparking.ownerconsole.modelo.PasoConfiguracion;
import mx.smartparking.ownerconsole.servicio.ValidadorConfiguracion;
import mx.smartparking.ownerconsole.vista.configuracion.FormularioAsistente;
import mx.smartparking.ownerconsole.vista.configuracion.VistaAsistente;

/** Mapea snapshots de vista al borrador y concentra validación por paso. */
final class CoordinadorFormularioAsistente {

    private final ValidadorConfiguracion validador = new ValidadorConfiguracion();

    void capturar(VistaAsistente vista, BorradorConfiguracion borrador) {
        FormularioAsistente formulario = vista.leerFormulario();
        try {
            borrador.actualizarIdentidad(
                    formulario.nombres().trim(),
                    formulario.primerApellido().trim(),
                    formulario.segundoApellido().trim());
            borrador.actualizarAcceso(formulario.correo().trim(), formulario.copiarContrasenaAcceso());
            borrador.actualizarAdministracion(
                    formulario.copiarContrasenaAdministrativa(), formulario.copiarConfirmacionAdministrativa());
            borrador.actualizarEstacionamiento(
                    formulario.nombreEstacionamiento().trim(), formulario.tipoEstacionamiento());
            borrador.actualizarHorario(
                    formulario.modoHorario(),
                    formulario.zonaHoraria().trim(),
                    formulario.horaApertura().trim(),
                    formulario.horaCierre().trim());
        } finally {
            formulario.limpiarSecretos();
        }
    }

    void restaurar(VistaAsistente vista, BorradorConfiguracion borrador) {
        FormularioAsistente formulario = crearFormulario(borrador);
        try {
            vista.restaurarFormulario(formulario);
        } finally {
            formulario.limpiarSecretos();
        }
    }

    void actualizarRevision(VistaAsistente vista, BorradorConfiguracion borrador) {
        FormularioAsistente formulario = crearFormulario(borrador);
        try {
            vista.actualizarRevision(formulario);
        } finally {
            formulario.limpiarSecretos();
        }
    }

    Map<String, String> validar(PasoConfiguracion paso, BorradorConfiguracion borrador) {
        return validador.validar(paso, borrador);
    }

    Map<String, String> validarTodo(BorradorConfiguracion borrador) {
        Map<String, String> errores = new LinkedHashMap<>();
        for (PasoConfiguracion paso : PasoConfiguracion.values()) {
            errores.putAll(validar(paso, borrador));
        }
        return errores;
    }

    int primerIndiceConError(Map<String, String> errores) {
        for (PasoConfiguracion paso : PasoConfiguracion.values()) {
            if (errores.keySet().stream().anyMatch(campo -> campoPertenece(paso, campo))) {
                return paso.ordinal();
            }
        }
        return 0;
    }

    Map<String, String> filtrarErrores(Map<String, String> errores, PasoConfiguracion paso) {
        Map<String, String> filtrados = new LinkedHashMap<>();
        errores.forEach((campo, texto) -> {
            if (campoPertenece(paso, campo)) {
                filtrados.put(campo, texto);
            }
        });
        return filtrados;
    }

    private FormularioAsistente crearFormulario(BorradorConfiguracion borrador) {
        FormularioAsistente formulario = new FormularioAsistente();
        formulario.actualizarIdentidad(
                borrador.nombres(), borrador.primerApellido(), borrador.segundoApellido());
        formulario.actualizarAcceso(borrador.correo(), borrador.copiarContrasenaAcceso());
        formulario.actualizarAdministracion(
                borrador.copiarContrasenaAdministrativa(), borrador.copiarConfirmacionAdministrativa());
        formulario.actualizarEstacionamiento(borrador.nombreEstacionamiento(), borrador.tipoEstacionamiento());
        formulario.actualizarHorario(
                borrador.modoHorario(), borrador.zonaHoraria(), borrador.horaApertura(), borrador.horaCierre());
        return formulario;
    }

    private boolean campoPertenece(PasoConfiguracion paso, String campo) {
        return switch (paso) {
            case IDENTIDAD -> campo.equals("nombres") || campo.equals("primerApellido") || campo.equals("segundoApellido");
            case ACCESO -> campo.equals("correo") || campo.equals("contrasenaAcceso");
            case ADMINISTRACION -> campo.equals("contrasenaAdministrativa") || campo.equals("confirmacionAdministrativa");
            case ESTACIONAMIENTO -> campo.equals("nombreEstacionamiento") || campo.equals("tipoEstacionamiento");
            case HORARIO -> campo.equals("zonaHoraria") || campo.equals("horaApertura") || campo.equals("horaCierre");
            case REVISION -> false;
        };
    }
}
