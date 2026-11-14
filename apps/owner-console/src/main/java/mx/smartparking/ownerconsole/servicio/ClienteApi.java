package mx.smartparking.ownerconsole.servicio;

import java.net.URI;
import java.util.UUID;

/** Reúne los clientes del propietario sobre un único transporte con sesión compartida. */
public final class ClienteApi {

    private final ClienteSesionPropietario sesion;
    private final ClienteConfiguracionPropietario configuracion;
    private final ClienteTransferenciaPropietario transferencia;

    public ClienteApi() {
        this(TransporteHttpPropietario.leerUrlBase());
    }

    ClienteApi(URI base) {
        TransporteHttpPropietario transporte = new TransporteHttpPropietario(base);
        sesion = new ClienteSesionPropietario(transporte);
        configuracion = new ClienteConfiguracionPropietario(transporte);
        transferencia = new ClienteTransferenciaPropietario(transporte);
    }

    public ClienteSesionPropietario sesion() {
        return sesion;
    }

    public ClienteConfiguracionPropietario configuracion() {
        return configuracion;
    }

    public ClienteTransferenciaPropietario transferencia() {
        return transferencia;
    }

    public String nuevoIdOperacion() {
        return UUID.randomUUID().toString();
    }
}

