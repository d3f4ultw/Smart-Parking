UPDATE idempotencia_registro_operador
SET estado = 'COMPLETADA', operador_id = ?
WHERE dueno_cuenta_id = ? AND clave_hash = ? AND estado = 'RESERVADA'
