UPDATE captura_rfid1
SET estado = ?, resultado = NULL, codigo_error = ?, actualizada_en = ?, terminada_en = ?
WHERE captura_id = ? AND estado = 'VISTA_PREVIA'
