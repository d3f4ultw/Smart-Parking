UPDATE captura_rfid1
SET estado = 'ESCANEANDO', request_id = ?, huella_uid = ?, resultado = NULL,
    codigo_error = 'TARJETA_YA_REGISTRADA', actualizada_en = ?
WHERE captura_id = ? AND estado IN ('PENDIENTE', 'ESCANEANDO')
