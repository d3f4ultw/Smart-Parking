SELECT clave_hash FROM idempotencia_accion_operador
WHERE operador_id = ? ORDER BY operacion, clave_hash FOR UPDATE
