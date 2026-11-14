package mx.smartparking.api.rfid1.modelo;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import mx.smartparking.api.configuracion.TipoEstacionamiento;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.Modalidad;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.Tarjeta;
import mx.smartparking.api.rfid1.modelo.ModeloTarjetasRfid1.VistaPrevia;
import mx.smartparking.api.rfid1.persistencia.RepositorioTarjetasRfid.TarjetaRfid1Persistida;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

class ModeloTarjetasRfid1Test {

    private static final String UID = "04A1B2C3";
    private static final JsonMapper JSON = JsonMapper.builder().build();

    @Test
    void uidSeConservaParaDuenoYVistaPreviaPeroEsNuloParaOperador() throws Exception {
        var tarjeta = new TarjetaRfid1Persistida(
                41, UID, "EMPLEADO", "E-0001", "Persona Prueba", "ACTIVA",
                Instant.parse("2026-10-28T12:00:00Z"), null);
        String historial = JSON.writeValueAsString(Tarjeta.desde(tarjeta));
        String historialOperador = JSON.writeValueAsString(Tarjeta.desde(tarjeta, false));
        String vistaPrevia = JSON.writeValueAsString(new VistaPrevia(
                UID, Instant.parse("2026-10-28T12:00:00Z"), Instant.parse("2026-10-28T12:05:00Z")));

        assertTrue(historial.contains(UID));
        assertTrue(historialOperador.contains("\"uid\":null"));
        assertFalse(historialOperador.contains(UID));
        assertTrue(vistaPrevia.contains(UID));
    }

    @Test
    void modalidadPublicaSoloElCampoNecesarioParaTarjetas() throws Exception {
        assertEquals("{\"tipoEstacionamiento\":\"MIXTO\"}",
                JSON.writeValueAsString(new Modalidad(TipoEstacionamiento.MIXTO)));
    }
}
