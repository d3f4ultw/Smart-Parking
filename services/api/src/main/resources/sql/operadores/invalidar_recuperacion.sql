UPDATE recuperacion_contrasena_operador SET consumido_en = ?
WHERE operador_id = ? AND consumido_en IS NULL
