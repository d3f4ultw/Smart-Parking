UPDATE configuracion_estacionamiento
SET tipo_estacionamiento = ?, modo_horario = ?, zona_horaria = ?,
    hora_apertura = ?, hora_cierre = ?, revision = ?,
    ultima_operacion_id = ?, ultima_clave_idempotencia_hash = ?
WHERE id = 1 AND estado = 'CONFIGURADA'
