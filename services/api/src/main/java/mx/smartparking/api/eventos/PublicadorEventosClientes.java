package mx.smartparking.api.eventos;

import org.springframework.stereotype.Component;

/** Avisa a las pantallas cuando se confirma un cambio que afecta la lista de clientes. */
@Component
public final class PublicadorEventosClientes {

    private final ServicioEventosAdministracion eventos;

    public PublicadorEventosClientes(ServicioEventosAdministracion eventos) {
        this.eventos = eventos;
    }

    public void clienteRegistrado() {
        eventos.publicarDirectorioActualizado(RegistroEventosAdministracion.NOMBRE_EVENTO_CLIENTE_REGISTRADO);
    }

    public void membresiaActualizada() {
        eventos.publicarDirectorioActualizado(
                RegistroEventosAdministracion.NOMBRE_EVENTO_MEMBRESIA_ACTUALIZADA);
    }
}
