UPDATE recuperacion_contrasena_operador SET consumido_en = ?
WHERE operador_id = ? AND token_hash = ? AND consumido_en IS NULL AND vence_en > ?
