UPDATE configuracion_estacionamiento
SET nombre_estacionamiento = ?, revision = ?, ultima_operacion_id = ?,
    ultima_clave_idempotencia_hash = ?
WHERE id = 1 AND estado = 'CONFIGURADA'
