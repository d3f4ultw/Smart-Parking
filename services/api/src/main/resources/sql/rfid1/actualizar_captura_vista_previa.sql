UPDATE captura_rfid1
SET estado = 'VISTA_PREVIA', request_id = ?, huella_uid = ?, resultado = 'PREVIEW_READY',
    codigo_error = NULL, actualizada_en = ?, previsualizada_en = ?, confirmacion_vence_en = ?
WHERE captura_id = ? AND estado IN ('PENDIENTE', 'ESCANEANDO') AND vence_en > ?
