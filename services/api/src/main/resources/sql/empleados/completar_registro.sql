UPDATE idempotencia_registro_empleado
SET estado = 'COMPLETADA', empleado_id = ?
WHERE cuenta_id = ? AND clave_hash = ? AND estado = 'RESERVADA'
