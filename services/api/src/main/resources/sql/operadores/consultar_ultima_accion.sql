SELECT creada_en FROM idempotencia_accion_operador
WHERE operador_id = ? AND operacion = ?
ORDER BY creada_en DESC LIMIT 1
