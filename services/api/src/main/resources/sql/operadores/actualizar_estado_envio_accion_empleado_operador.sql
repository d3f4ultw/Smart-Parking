UPDATE idempotencia_accion_empleado_operador
SET estado_envio = ?
WHERE dueno_cuenta_id = ? AND clave_hash = ? AND estado = 'COMPLETADA'
