SELECT count(*) FROM idempotencia_accion_operador
WHERE operador_id = ? AND operacion = ? AND creada_en >= ?
