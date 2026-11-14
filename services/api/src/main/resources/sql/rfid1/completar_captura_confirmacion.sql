UPDATE captura_rfid1
SET estado = 'COMPLETADA', resultado = 'ASOCIADA', codigo_error = NULL,
    terminada_en = ?, actualizada_en = ?, hash_clave_confirmacion = ?,
    codigo_confirmacion = NULL, asociacion_confirmada_id = ?
WHERE captura_id = ? AND estado = 'VISTA_PREVIA'
