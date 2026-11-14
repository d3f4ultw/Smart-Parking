UPDATE idempotencia_accion_empleado_operador
SET estado = 'COMPLETADA', operador_id = ?, estado_operador = ?,
    revision_empleado = ?, estado_envio = ?
WHERE dueno_cuenta_id = ? AND clave_hash = ? AND estado = 'RESERVADA'
