package mx.smartparking.api.rfid1.modelo;

import java.time.Instant;
import mx.smartparking.api.rfid1.persistencia.RepositorioRfid1.CapturaRfid1Persistida;

/** Reúne los datos de una lectura de tarjeta que la cuenta autorizada puede consultar. */
public record CapturaRfid1(
        String capturaId,
        String tipoEntidad,
        String codigoPersona,
        String estado,
        Instant expiraEn,
        Instant confirmacionVenceEn,
        String resultado,
        String codigoError) {

    public static CapturaRfid1 desde(CapturaRfid1Persistida captura) {
        return new CapturaRfid1(
                captura.capturaId(), captura.tipoEntidad(), captura.codigoPersona(), captura.estado(),
                captura.venceEn(), captura.confirmacionVenceEn(), captura.resultado(), captura.codigoError());
    }
}
