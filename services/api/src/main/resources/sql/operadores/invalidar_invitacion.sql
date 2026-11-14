UPDATE invitacion_operador SET consumido_en = ?
WHERE operador_id = ? AND consumido_en IS NULL
