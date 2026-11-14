UPDATE idempotencia_accion_operador SET estado_envio = ?
WHERE operador_id = ? AND operacion = ? AND clave_hash = ? AND estado_envio = 'ENVIANDO'
