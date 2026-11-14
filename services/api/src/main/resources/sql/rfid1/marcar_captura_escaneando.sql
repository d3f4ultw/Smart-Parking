UPDATE captura_rfid1 SET estado = 'ESCANEANDO', actualizada_en = ?
WHERE captura_id = ? AND estado = 'PENDIENTE' AND vence_en > ?
